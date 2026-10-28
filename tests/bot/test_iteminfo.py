from bot import iteminfo, render
from bot.iteminfo import CLASSIC, FOREVER, ItemInfo

from .conftest import TZ, link

# What nether.wowhead.com/forever/tooltip/item/873 answers (shortened).
STAFF = {
    "name": "Staff of Jordan", "quality": 4, "icon": "inv_staff_13",
    "tooltip": '<table><tr><td><!--nstart--><b class="q4">Staff of Jordan</b><!--nend--><span class="q"><br>'
               'Item Level <!--ilvl-->40</span><!--bo--><br>Binds when equipped<table width="100%"><tr>'
               '<td>Two-Hand</td><th><!--scstart2:10--><span class="q1">Staff</span><!--scend--></th></tr></table>'
               '<!--rf--><table width="100%"><tr>\n    <td><span><!--dmg-->88 - 133 Damage</span></td>\n'
               '    <th>Speed <!--spd-->3.70</th>\n</tr></table></td></tr></table>',
}
GLOVES = {"name": "Felheart Gloves", "quality": 4, "icon": "inv_gauntlets_19",
          "tooltip": '<table width="100%"><tr><td>Hands</td><th><span class="q1">Cloth</span></th></tr></table>'}


def test_parse_takes_quality_from_forever_only():
    assert iteminfo.parse(STAFF, FOREVER) == ItemInfo(found=True, env=FOREVER, name="Staff of Jordan", quality=4,
                                                      icon="inv_staff_13", slot="Two-Hand · Staff")
    assert iteminfo.parse(GLOVES, CLASSIC).quality is None  # Classic's may be Season of Discovery's
    assert iteminfo.parse({"name": "Ring", "icon": "../evil"}, FOREVER).icon is None


def test_urls():
    assert iteminfo.icon_url("inv_staff_13") == "https://wow.zamimg.com/images/wow/icons/large/inv_staff_13.jpg"
    assert iteminfo.page_url(873, "Staff of Jordan") == "https://www.wowhead.com/forever/item=873/staff-of-jordan"
    assert iteminfo.page_url(17076, "Bonereaver's Edge", CLASSIC) == \
        "https://www.wowhead.com/classic/item=17076/bonereavers-edge"
    assert iteminfo.slug("Sulfuras, Hand of Ragnaros") == "sulfuras-hand-of-ragnaros"


class FakeResponse:
    def __init__(self, status, data=None):
        self.status, self.data = status, data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self, content_type=None):
        return self.data


class FakeSession:
    def __init__(self, pages):
        self.pages, self.asked = pages, []

    def get(self, url, timeout=None):
        self.asked.append(url)
        return FakeResponse(*self.pages.get(url, (404, {"error": "Entity not found"})))


async def test_fetch_asks_forever_then_classic():
    forever = iteminfo.TOOLTIP_URL.format(env=FOREVER, id=873)
    classic = iteminfo.TOOLTIP_URL.format(env=CLASSIC, id=16805)
    session = FakeSession({forever: (200, STAFF), classic: (200, GLOVES)})
    assert (await iteminfo.fetch(session, 873)).env == FOREVER
    assert session.asked == [forever]
    gloves = await iteminfo.fetch(session, 16805)
    assert (gloves.env, gloves.icon, gloves.quality) == (CLASSIC, "inv_gauntlets_19", None)
    assert await iteminfo.fetch(session, 18000) == ItemInfo(found=False)
    assert await iteminfo.fetch(FakeSession({iteminfo.TOOLTIP_URL.format(env=FOREVER, id=1): (503, None)}), 1) is None


def test_store_asks_again_daily_until_forever_has_it(store, clock):
    for item_id in (873, 16805, 99999):
        store.add_item(item_id, f"Item {item_id}")
    assert store.items_to_look_up() == [873, 16805, 99999]
    store.save_item_info(873, iteminfo.parse(STAFF, FOREVER))
    store.save_item_info(16805, iteminfo.parse(GLOVES, CLASSIC))
    store.save_item_info(99999, ItemInfo(found=False))
    assert store.items_to_look_up() == []
    clock.t += iteminfo.RETRY_SECONDS
    assert store.items_to_look_up() == [16805, 99999]


def test_item_state_gets_the_icon_slot_quality_and_link(store):
    store.add_item(873, "Staff of Jordan")
    store.save_item_info(873, iteminfo.parse(STAFF, FOREVER))
    assert store.icons_without_emoji() == ["inv_staff_13"]
    store.save_icon_emoji("inv_staff_13", "<:inv_staff_13:42>")
    s = store.item_state(873)
    assert (s.icon, s.emoji, s.quality, s.slot) == ("inv_staff_13", "<:inv_staff_13:42>", 4, "Two-Hand · Staff")
    assert store.icons_without_emoji() == []
    card = render.officer_card(s, TZ)
    assert card.head().startswith(
        "### <:inv_staff_13:42> [Staff of Jordan](https://www.wowhead.com/forever/item=873/staff-of-jordan)")
    assert card.colour == 0xA335EE
    # A slot typed in with /loot add wins over Wowhead's.
    store.add_item(873, "Staff of Jordan", slot="Two-Hand · Staff (Forever)")
    assert store.item_state(873).slot == "Two-Hand · Staff (Forever)"


def test_the_games_quality_wins_over_wowheads(store):
    store.add_item(16805, "Felheart Gloves", quality=4)
    store.save_item_info(16805, ItemInfo(found=True, env=FOREVER, name="Felheart Gloves", quality=3))
    assert store.item_state(16805).quality == 3  # Forever's data beats /loot add's guess
    store.conn.execute("UPDATE items SET link = ?, quality = 4 WHERE id = 16805", (link(16805, "Felheart Gloves"),))
    assert store.item_state(16805).quality == 4  # the game's beats both


def test_classic_only_item_links_to_classic(store):
    store.add_item(16805, "Felheart Gloves")
    store.save_item_info(16805, iteminfo.parse(GLOVES, CLASSIC))
    assert render.items_card(store.item_state(16805), TZ).url == \
        "https://www.wowhead.com/classic/item=16805/felheart-gloves"


def test_unknown_item_has_no_link_or_icon(store):
    store.add_item(99999, "Forever's own")
    store.save_item_info(99999, ItemInfo(found=False))
    card = render.items_card(store.item_state(99999), TZ)
    assert (card.url, card.emoji) == ("", "")
    assert card.head() == "### Forever's own"
