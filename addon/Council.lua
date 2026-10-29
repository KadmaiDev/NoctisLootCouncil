-- The loot council, for council items. The loot master starts it (/nlc start, or the loot
-- window's button); then:
--   1. Bids, 30 seconds. Raiders with the addon get the pop-up: Main spec / Off spec / Pass,
--      optional tags (BIS, Big upgrade, Sidegrade, Situational) and a note; their bid, their
--      upgrade % and what they wear in that slot go to the loot master and the council only.
--      Raiders without the addon bid by rolling: /roll main spec, /roll 99 off spec.
--   2. The council votes, 5 minutes at most (the loot master's clock). One vote each,
--      changeable, with at least one reason from the rules (class fit, biggest upgrade, less
--      loot so far, reliability, effort); a council member who bid main spec sits out (their
--      own loot). It ends early once everyone who can vote has.
--   3. A clear winner (most votes) gets it, with the votes and their voters' reasons as the
--      reason in the loot log ("council vote, 2 of 3: biggest upgrade"). A tie, or no votes,
--      goes to a roll-off between the top candidates. The loot master can also award any
--      candidate from the window, with a reason.
-- Shortcuts (the rules): one main-spec bid gets it without a vote; no main-spec bids and
-- some off-spec ones roll off between those; no bids at all, and the loot master
-- disenchants or banks it.
--
-- The council is /nlc councillors (on the loot master's addon; it's sent with each item).
-- Each council member's addon keeps the same session from the messages, to show the window;
-- only the loot master's decides.
local ADDON, ns = ...
if ns.disabled then return end
local L = ns.L

local time, tonumber, tostring, type, ipairs, pairs, concat, sort = time, tonumber, tostring, type, ipairs, pairs, table.concat, table.sort

local BIDS = 30
local VOTE = 300
local WARN = 10
ns.BID_TAGS = { L["BIS"], L["Big upgrade"], L["Sidegrade"], L["Situational"] }
ns.NOTE_MAX = 60
-- Why a council member votes as they do: the rules' criteria, in the rules' order. The key
-- goes in the vote message, the text in the loot log.
ns.VOTE_REASONS = {
    { key = "fit", label = L["Class fit"], text = L["class fit"] },
    { key = "upgrade", label = L["Biggest upgrade"], text = L["biggest upgrade"] },
    { key = "loot", label = L["Less loot so far"], text = L["less loot so far"] },
    { key = "reliable", label = L["Reliability"], text = L["reliability"] },
    { key = "effort", label = L["Effort"], text = L["effort"] },
}
local REASON = {} -- key -> position in VOTE_REASONS
for i, r in ipairs(ns.VOTE_REASONS) do REASON[r.key] = i end

-- { sid, id, link, lm = name, council = { names }, voters = { [key] = true }, bids = { [key] = bid },
--   votes = { [voterKey] = candidateKey }, why = { [voterKey] = { reason keys } }, myWhy = { [reason
--   key] = true } (this player's ticks), phase = "bids"|"vote"|"rolloff"|"done", mine = true on
--   the loot master's addon, ends = time() the phase ends, winner }
-- bid = { name, key, unit, resp = "ms"|"os", tags, note, gain (number|nil), gear = { itemIDs }, roll }
local session
local token = 0

function ns.CouncilSession() return session end

local function Changed()
    if ns.CouncilChanged then ns.CouncilChanged() end
end

local function Me() return ns.NameKey(ns.PlayerName()) end

-- The loot master and every council member: who bids and votes are sent to.
local function Recipients(s)
    local list, seen = {}, {}
    for _, name in ipairs({ s.lm, unpack(s.council) }) do
        local key = ns.NameKey(name)
        if key and not seen[key] then
            seen[key] = true
            list[#list + 1] = name
        end
    end
    return list
end
function ns.CouncilRecipients() return session and Recipients(session) end

-- Can this council member vote on this item? Not if they bid main spec on it.
function ns.CanVote(s, key)
    if not s.voters[key] then return false end
    local bid = s.bids[key]
    return not (bid and bid.resp == "ms")
end

function ns.Candidates(s)
    local list = {}
    for _, b in pairs(s.bids) do list[#list + 1] = b end
    sort(list, function(a, b)
        if a.resp ~= b.resp then return a.resp == "ms" end
        local x, y = a.gain or -1, b.gain or -1
        if x ~= y then return x > y end
        return a.key < b.key
    end)
    return list
end

-- Votes per candidate key, and how many have voted.
function ns.Tally(s)
    local counts, n = {}, 0
    for voter, cand in pairs(s.votes) do
        if ns.CanVote(s, voter) and s.bids[cand] then
            counts[cand] = (counts[cand] or 0) + 1
            n = n + 1
        end
    end
    return counts, n
end

local function Eligible(s)
    local n = 0
    for key in pairs(s.voters) do
        if ns.CanVote(s, key) then n = n + 1 end
    end
    return n
end

---------------------------------------------------------------------------
-- Bids
---------------------------------------------------------------------------
local function Split(text)
    local list = {}
    for part in (text or ""):gmatch("[^,]+") do list[#list + 1] = part end
    return list
end

local function AddBid(m, resp, tags, note, gain, gear, roll)
    local s = session
    if resp == "pass" then
        s.bids[m.key] = nil
    else
        local b = s.bids[m.key] or { name = m.name, key = m.key, unit = m.unit }
        b.resp = resp
        b.tags = tags or b.tags
        b.note = note or b.note
        b.gain = gain or b.gain
        b.gear = gear or b.gear
        b.roll = roll or b.roll
        b.trial = m.unit and ns.IsTrial(m.unit) or false
        s.bids[m.key] = b
    end
    Changed()
end

ns.OnMessage("B", function(m, sid, resp, tags, note, gain, gear)
    local s = session
    if not s or tonumber(sid) ~= s.sid or s.phase ~= "bids" then return end
    if resp ~= "ms" and resp ~= "os" and resp ~= "pass" then return end
    local g = tonumber(gain)
    if gain == "new" then g = math.huge end
    local ids = {}
    for _, id in ipairs(Split(gear)) do ids[#ids + 1] = tonumber(id) end
    note = note and note:sub(1, ns.NOTE_MAX) or nil
    AddBid(m, resp, Split(tags), note ~= "" and note or nil, g, ids)
end)

-- Raiders without the addon bid by rolling; a roll from someone who bid with the pop-up is
-- kept with their bid.
ns.On("CHAT_MSG_SYSTEM", function(text)
    local s = session
    if not s or s.phase ~= "bids" then return end
    local m, roll, low, high = ns.ParseRoll(text)
    if not m or low ~= 1 or (high ~= 100 and high ~= 99) then return end
    local b = s.bids[m.key]
    if b then
        b.roll = b.roll or roll
        Changed()
    else
        AddBid(m, high == 100 and "ms" or "os", nil, nil, nil, nil, roll)
    end
end)

---------------------------------------------------------------------------
-- Votes
---------------------------------------------------------------------------
local Tally

-- Known reason keys from a message, once each, in the rules' order.
local function Reasons(text)
    local keys, seen = {}, {}
    for _, key in ipairs(Split(text)) do
        if REASON[key] and not seen[key] then
            seen[key] = true
            keys[#keys + 1] = key
        end
    end
    sort(keys, function(a, b) return REASON[a] < REASON[b] end)
    return keys
end

ns.OnMessage("V", function(m, sid, cand, why)
    local s = session
    if not s or tonumber(sid) ~= s.sid or s.phase ~= "vote" or not ns.CanVote(s, m.key) then return end
    -- A vote needs a reason from the rules (an older addon, or a made-up message, may send none).
    local reasons = cand ~= "" and Reasons(why) or nil
    if reasons and #reasons == 0 then
        if s.mine then ns.Say(L["%s's vote has no reason, so it doesn't count: they may need to update the addon."]:format(m.name)) end
        return
    end
    s.votes[m.key] = cand ~= "" and cand or nil
    s.why[m.key] = reasons
    Changed()
    if s.mine then
        local _, n = ns.Tally(s)
        if n >= Eligible(s) then Tally(false) end
    end
end)

-- This player's ticked reasons, in the rules' order.
local function MyWhy(s)
    local keys = {}
    for _, r in ipairs(ns.VOTE_REASONS) do
        if s.myWhy and s.myWhy[r.key] then keys[#keys + 1] = r.key end
    end
    return keys
end

-- Votes are never sent raid-wide: if a whisper fails, the council member is told.
local function VoteSent(missed)
    if not missed then return end
    ns.Say(L["Couldn't send your vote privately to %s. Whisper the loot master your vote and why; they can award it with /nlc award."]:format(concat(missed, ", ")))
end

-- This council member's vote (nil takes it back). A vote needs at least one reason ticked.
function ns.Vote(candKey)
    local s = session
    if not s or s.phase ~= "vote" then return false end
    local why = MyWhy(s)
    if candKey and #why == 0 then
        ns.Say(L["Tick at least one reason first: it's posted in the loot log."])
        return false
    end
    VoteSent(ns.SendTo(Recipients(s), "V", s.sid, candKey or "", candKey and concat(why, ",") or ""))
    return true
end

-- Ticks or unticks a reason; a vote already cast is sent again with the new reasons.
function ns.SetVoteReason(key, on)
    local s = session
    if not s or not REASON[key] then return end
    s.myWhy = s.myWhy or {}
    s.myWhy[key] = on or nil
    local cand = s.phase == "vote" and s.votes[Me()]
    if cand and #MyWhy(s) > 0 then
        VoteSent(ns.SendTo(Recipients(s), "V", s.sid, cand, concat(MyWhy(s), ",")))
    end
    Changed()
end

-- "council vote, 2 of 3: biggest upgrade, less loot so far": the reasons given by at least
-- half of those who voted for the winner, the most given first.
local function VoteReason(s, cand, best, n)
    local count, keys = {}, {}
    for voter, c in pairs(s.votes) do
        if c == cand and ns.CanVote(s, voter) then
            for _, key in ipairs(s.why[voter] or {}) do count[key] = (count[key] or 0) + 1 end
        end
    end
    for key, c in pairs(count) do
        if c * 2 >= best then keys[#keys + 1] = key end
    end
    sort(keys, function(a, b)
        if count[a] ~= count[b] then return count[a] > count[b] end
        return REASON[a] < REASON[b]
    end)
    local text = L["council vote, %d of %d"]:format(best, n)
    if #keys == 0 then return text end
    local words = {}
    for i, key in ipairs(keys) do words[i] = ns.VOTE_REASONS[REASON[key]].text end
    return text .. ": " .. concat(words, ", ")
end

---------------------------------------------------------------------------
-- The loot master's side
---------------------------------------------------------------------------
local function After(seconds, fn)
    token = token + 1
    local mine, s = token, session
    if C_Timer and C_Timer.After then
        C_Timer.After(seconds, function()
            if session == s and token == mine then fn() end
        end)
    end
end

local function Phase(s, phase, seconds)
    s.phase = phase
    s.ends = seconds and time() + seconds or nil
    Changed()
end

local function End(s, winner)
    s.winner = winner
    Phase(s, "done")
    ns.Broadcast("E", s.sid, winner or "")
end

local function Wanted(s)
    local ms, os = 0, 0
    for _, b in pairs(s.bids) do
        if b.resp == "ms" then ms = ms + 1 else os = os + 1 end
    end
    return ms, os
end

-- Awards it to a candidate with a reason (their tags and note are added to the log's). An
-- off-spec roll-off's roll goes in the log too, as a roll item's does.
function ns.CouncilAward(candKey, reason, roll)
    local s = session
    if not s or not s.mine or s.phase == "done" then return false end
    local b = s.bids[candKey]
    if not b then return false end
    reason = reason and reason:match("^%s*(.-)%s*$") or ""
    if reason == "" then reason = L["council decision"] end
    local bid = {}
    if b.tags and #b.tags > 0 then bid[#bid + 1] = concat(b.tags, ", ") end
    if b.note then bid[#bid + 1] = '"' .. b.note .. '"' end
    local note = #bid > 0 and reason .. "; " .. L["bid: %s"]:format(concat(bid, " ")) or reason
    local ms, os = Wanted(s)
    ns.LogAward({ id = s.id, link = s.link, who = b.name, how = b.resp == "os" and "os" or "council",
        roll = b.resp == "os" and roll or nil, note = note, nms = ms, nos = os, tags = b.tags and #b.tags > 0 and concat(b.tags, ", ") or nil }, b.unit)
    ns.Announce(L["%s wins %s (council: %s)."]:format(b.name, s.link, reason))
    End(s, b.name)
    return true
end

local function RollOff(s, keys, reasonFmt)
    local only, names = {}, {}
    for _, key in ipairs(keys) do
        only[key] = true
        names[#names + 1] = s.bids[key].name
    end
    sort(names)
    Phase(s, "rolloff")
    local ok = ns.StartRoll(s.id, s.link, { only = only, names = names,
        onAward = function(e, roll) ns.CouncilAward(e.key, reasonFmt:format(roll), roll) end,
        onNobody = function() End(s) end,
        -- Called off, or a tie nobody re-rolled: back to the vote, for the loot master to award
        -- it from the window (or /nlc award), roll off again, or call it off.
        onCancel = function()
            if session ~= s or s.phase ~= "rolloff" then return end
            Phase(s, "vote")
            ns.Say(L["The roll-off for %s is off. Award it from the council window (or /nlc award), roll off again, or /nlc cancel."]:format(s.link))
        end })
    if not ok then
        ns.Say(L["A roll is running; finish it, then award %s from the council window."]:format(s.link))
        Phase(s, "vote")
    end
end

Tally = function(timeUp)
    local s = session
    if not s or s.phase ~= "vote" then return end
    local counts, n = ns.Tally(s)
    local top, best, tied = nil, 0, {}
    for key, c in pairs(counts) do
        if c > best then top, best, tied = key, c, { key } elseif c == best then tied[#tied + 1] = key end
    end
    if top and #tied == 1 then
        return ns.CouncilAward(top, VoteReason(s, top, best, n))
    end
    if not timeUp and n < Eligible(s) then return end
    if #tied == 0 then -- nobody voted: every main-spec candidate rolls
        for _, b in ipairs(ns.Candidates(s)) do
            if b.resp == "ms" then tied[#tied + 1] = b.key end
        end
    end
    sort(tied)
    ns.Announce(L["The council is split on %s."]:format(s.link))
    RollOff(s, tied, L["roll-off after a split vote, %d"])
end

local function CloseBids()
    local s = session
    if not s or s.phase ~= "bids" then return end
    local ms, os = {}, {}
    for key, b in pairs(s.bids) do
        if b.resp == "ms" then ms[#ms + 1] = key else os[#os + 1] = key end
    end
    sort(ms)
    sort(os)
    if #ms == 1 then
        Phase(s, "vote")
        return ns.CouncilAward(ms[1], L["the only main-spec bid"])
    end
    if #ms == 0 and #os > 0 then
        ns.Announce(L["No main-spec bids for %s; off spec rolls."]:format(s.link))
        return RollOff(s, os, L["off-spec roll, %d"])
    end
    if #ms == 0 then
        ns.Announce(L["Nobody wants %s: the loot master disenchants or banks it."]:format(s.link))
        return End(s)
    end
    Phase(s, "vote", VOTE)
    ns.Announce(L["Bids closed for %s: %d main spec. The council has %d minutes."]:format(s.link, #ms, VOTE / 60))
    ns.Broadcast("P", s.sid, "vote", VOTE) -- nothing private: the vote has started
    After(VOTE, function() Tally(true) end)
end

function ns.StartCouncil(id, link)
    if session and session.phase ~= "done" then
        ns.Say(L["The council is still on %s. /nlc stop moves it on, /nlc cancel calls it off."]:format(session.link))
        return false
    end
    local me = ns.PlayerName()
    local council = {}
    for _, name in ipairs(ns.db.council or {}) do council[#council + 1] = name end
    if #council == 0 then
        council[1] = me
        ns.Say(L["No council set (/nlc councillors), so you decide alone."])
    end
    local voters = {}
    for _, name in ipairs(council) do voters[ns.NameKey(name)] = true end
    session = { sid = ns.NewSession(), id = id, link = link, lm = me, council = council, voters = voters,
        bids = {}, votes = {}, why = {}, mine = true }
    Phase(session, "bids", BIDS)
    ns.Announce(L["Council item: %s. Use the pop-up, or /roll for main spec, /roll 99 for off spec. %d seconds."]:format(link, BIDS))
    ns.SendSession(session)
    After(BIDS - WARN, function() ns.Announce(L["%d seconds left to bid on %s."]:format(WARN, link)) end)
    -- Its own timer token: the warning's would replace it.
    local s = session
    if C_Timer and C_Timer.After then
        C_Timer.After(BIDS, function()
            if session == s and s.phase == "bids" then CloseBids() end
        end)
    end
    if ns.ShowCouncilWindow then ns.ShowCouncilWindow() end
    return true
end

-- The session start, raid-wide: the link goes last and is dropped if the message would be
-- too long (raiders' addons look the item up by its ID then).
function ns.SendSession(s)
    local council = concat(s.council, ",")
    if #ns.Encode("S", s.sid, s.id, "council", BIDS, s.lm, council, s.link) <= 255 then
        ns.Broadcast("S", s.sid, s.id, "council", BIDS, s.lm, council, s.link)
    else
        ns.Broadcast("S", s.sid, s.id, "council", BIDS, s.lm, council)
    end
end

function ns.StopCouncil()
    local s = session
    if not s or not s.mine or s.phase == "done" or s.phase == "rolloff" then return false end
    if s.phase == "bids" then CloseBids() else Tally(true) end
    return true
end

function ns.CancelCouncil()
    local s = session
    if not s or not s.mine or s.phase == "done" or s.phase == "rolloff" then return false end
    ns.Announce(L["Council for %s called off."]:format(s.link))
    End(s)
    return true
end

-- Starts a roll-off between these candidates from the window.
function ns.CouncilRollOff(keys)
    local s = session
    if not s or not s.mine or s.phase ~= "vote" or #keys < 2 then return false end
    sort(keys)
    RollOff(s, keys, L["roll-off, %d"])
    return true
end

---------------------------------------------------------------------------
-- A council member's side: the session from the loot master's messages
---------------------------------------------------------------------------
ns.OnMessage("S", function(m, sid, id, kind, seconds, lm, council, link)
    if kind ~= "council" then return end
    -- Only from the loot master it names, who must be able to run the loot.
    if ns.NameKey(lm) ~= m.key or not ns.MayRunLoot(m.unit) then return end
    sid, id = tonumber(sid), tonumber(id)
    if not sid or (session and session.sid == sid) then return end
    -- An open session is only replaced by its own loot master moving on to the next item.
    if session and session.phase ~= "done" and (session.mine or ns.NameKey(session.lm) ~= m.key) then return end
    local names = Split(council)
    local me, voters, member = Me(), {}, false
    for _, name in ipairs(names) do
        voters[ns.NameKey(name)] = true
        if ns.NameKey(name) == me then member = true end
    end
    if not member or ns.NameKey(lm) == me then return end
    local item = id and ns.db.items[id]
    session = { sid = sid, id = id, link = link ~= "" and link or (item and item.link) or ("item:" .. tostring(id)),
        lm = lm, council = names, voters = voters, bids = {}, votes = {}, why = {} }
    Phase(session, "bids", tonumber(seconds) or BIDS)
    if ns.ShowCouncilWindow then ns.ShowCouncilWindow() end
end)

ns.OnMessage("P", function(m, sid, phase, seconds)
    local s = session
    if not s or s.mine or tonumber(sid) ~= s.sid or phase ~= "vote" or m.key ~= ns.NameKey(s.lm) then return end
    Phase(s, "vote", tonumber(seconds))
end)

ns.OnMessage("E", function(m, sid, winner)
    local s = session
    if not s or s.mine or tonumber(sid) ~= s.sid or m.key ~= ns.NameKey(s.lm) then return end
    s.winner = winner ~= "" and winner or nil
    Phase(s, "done")
end)

---------------------------------------------------------------------------
-- Commands
---------------------------------------------------------------------------
ns.Command("councillors", function(text)
    if text:lower() == "none" then
        ns.db.council = nil
    elseif text ~= "" then
        local list = {}
        for name in text:gmatch("[^,]+") do
            name = name:match("^%s*(.-)%s*$")
            if name ~= "" then list[#list + 1] = name end
        end
        ns.db.council = list
    end
    if ns.db.council then
        ns.Say(L["Council: %s."]:format(concat(ns.db.council, ", ")))
    else
        ns.Say(L["No council set: the loot master decides council items alone."])
    end
end, L["[First Last, First Last, ...|none]: who votes on council items"])

ns.Command("award", function(text)
    local s = session
    if not s or not s.mine or s.phase ~= "vote" then
        ns.Say(L["No council vote running."])
        return
    end
    local name, reason = text:match("^([^,]+),?%s*(.*)$")
    local key = name and ns.NameKey(name)
    if not key or not s.bids[key] then
        ns.Say(L["Not a candidate: %s."]:format(name or ""))
        return
    end
    ns.CouncilAward(key, reason)
end, L["<First Last>[, reason]: award the council item to a candidate"])
