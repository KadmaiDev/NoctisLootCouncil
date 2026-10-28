from bot import iteminfo, render
from bot.iteminfo import ItemInfo

from .conftest import TZ

# What nether.wowhead.com/classic/tooltip/item/873 answers (shortened).
STAFF = {
    "name": "Staff of Jordan", "quality": 4, "icon": "inv_staff_13",
    "tooltip": '<table><tr><td><!--nstart--><b class="q4">Staff of Jordan</b><!--nend--><span class="q"><br>'
               'Item Level <!--ilvl-->40</span><!--bo--><br>Binds when equipped<table width="100%"><tr>'
               '<td>Two-Hand</td><th><!--scstart2:10--><span class="q1">Staff</span><!--scend--></th></tr></table>'
               '<!--rf--><table width="100%"><tr>\n    <td><span><!--dmg-->119 - 180 Damage</span></td>\n'
               '    <th>Speed <!--spd-->3.70</th>\n</tr></table></td></tr></table>',
}


def test_parse_takes_the_icon_and_slot_only():
    assert iteminfo.parse(STAFF) == ItemInfo(found=True, icon="inv_staff_13", slot="Two-Hand · Staff")
    assert iteminfo.parse({"name": "Ring", "icon": "../evil", "tooltip": ""}) == ItemInfo(found=True)


def test_urls():
    assert iteminfo.icon_url("inv_staff_13") == "https://wow.zamimg.com/images/wow/icons/large/inv_staff_13.jpg"
    assert iteminfo.page_url(873) == "https://www.wowhead.com/classic/item=873"


def test_store_looks_items_up_once_and_unknown_ones_again_a_day_later(store, clock):
    store.add_item(873, "Staff of Jordan")
    store.add_item(99999, "Forever's own")
    assert store.items_to_look_up() == [873, 99999]
    store.save_item_info(873, iteminfo.parse(STAFF))
    store.save_item_info(99999, ItemInfo(found=False))
    assert store.items_to_look_up() == []
    clock.t += iteminfo.RETRY_SECONDS
    assert store.items_to_look_up() == [99999]


def test_item_state_gets_the_icon_slot_and_link(store):
    store.add_item(873, "Staff of Jordan")
    store.save_item_info(873, iteminfo.parse(STAFF))
    assert store.icons_without_emoji() == ["inv_staff_13"]
    store.save_icon_emoji("inv_staff_13", "<:inv_staff_13:42>")
    s = store.item_state(873)
    assert (s.icon, s.emoji, s.on_wowhead, s.slot) == ("inv_staff_13", "<:inv_staff_13:42>", True, "Two-Hand · Staff")
    assert store.icons_without_emoji() == []
    card = render.officer_card(s, TZ)
    assert card.head().startswith("### [Staff of Jordan](https://www.wowhead.com/classic/item=873)")
    assert card.icon_url.endswith("/inv_staff_13.jpg")
    # A slot typed in with /loot add wins over Wowhead's.
    store.add_item(873, "Staff of Jordan", slot="Two-Hand · Staff (Forever)")
    assert store.item_state(873).slot == "Two-Hand · Staff (Forever)"


def test_unknown_item_has_no_link_or_icon(store):
    store.add_item(99999, "Forever's own")
    store.save_item_info(99999, ItemInfo(found=False))
    card = render.items_card(store.item_state(99999), TZ)
    assert (card.url, card.icon_url) == ("", "")
    assert card.head() == "### Forever's own"
