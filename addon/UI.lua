-- Windows: the look of the player's UI addon, our own window size, and the Gamepad UI. Ported
-- from Alts Forever (Skin.lua, Options.lua's scale, Gamepad.lua), trimmed to what our windows
-- use.
--  * EllesmereUI (with its third-party skinning on for us): through its public skinning API;
--    ElvUI: through its Skins module. Without either, the game's own look stays.
--  * Size: db.scale (0.5-3, /nlc scale), or EllesmereUI's Window Scale if it's installed, else 1.
--  * Gamepad UI (Forever's Alpha): our windows join Blizzard's focus manager, so the D-pad
--    reaches their buttons and B closes them. Undocumented internals: every name is checked.
local ADDON, ns = ...
if ns.disabled then return end
local L = ns.L

local ipairs, select, pcall, type, tonumber = ipairs, select, pcall, type, tonumber
local floor, max, min = math.floor, math.max, math.min

---------------------------------------------------------------------------
-- Skins
---------------------------------------------------------------------------
local skin -- EllesmereUI's skinning facade, once it hands it to us

local elvE, elvS
local function Elv()
    if skin then return nil end
    if elvS then return elvE, elvS end
    local engine = _G.ElvUI
    local E = type(engine) == "table" and engine[1]
    if type(E) ~= "table" or not E.Initialized or type(E.GetModule) ~= "function" then return nil end
    local ok, S = pcall(E.GetModule, E, "Skins", true)
    if not (ok and type(S) == "table" and S.HandleFrame) then return nil end
    elvE, elvS = E, S
    return E, S
end

local function ElvFont(fs)
    if not fs.FontTemplate then return end
    local size = fs.GetFont and select(2, fs:GetFont())
    fs:FontTemplate(nil, type(size) == "number" and size or nil)
end

function ns.SkinText(fs)
    if not fs then return end
    if skin then
        skin.Font(fs)
    elseif Elv() then
        pcall(ElvFont, fs)
    end
end

local function SkinRegions(frame, font)
    for i = 1, select("#", frame:GetRegions()) do
        local region = select(i, frame:GetRegions())
        if region and region.GetObjectType and region:GetObjectType() == "FontString" then font(region) end
    end
end

local TITLE_Y = -14

function ns.SkinWindow(f, opts)
    if not f then return end
    if skin then
        skin.Shell(f, opts)
        if f.CloseButton then skin.CloseButton(f.CloseButton) end
        if f.Inset then skin.Inset(f.Inset) end
        -- The title's letters in the middle of the shell's title strip (Alts Forever, measured).
        if f.TitleText then
            f.TitleText:ClearAllPoints()
            f.TitleText:SetPoint("CENTER", f, "TOP", 0, TITLE_Y)
        end
        SkinRegions(f, skin.Font)
    elseif Elv() then
        pcall(function()
            elvS:HandleFrame(f)
            SkinRegions(f, ElvFont)
        end)
    end
end

function ns.SkinButton(b)
    if not b then return end
    if skin then
        if skin.Button then pcall(skin.Button, b) end
    elseif Elv() then
        pcall(elvS.HandleButton, elvS, b)
    end
end

function ns.SkinEditBox(e)
    if not e then return end
    if skin then
        if skin.EditBox then pcall(skin.EditBox, e, { padInput = true }) end
    elseif Elv() then
        pcall(elvS.HandleEditBox, elvS, e)
    end
end

local windows = {} -- every window of ours, for skinning late and for the size

if EllesmereUI and EllesmereUI.RegisterSkin then
    EllesmereUI.RegisterSkin(ADDON, function(S)
        skin = S
        for _, f in ipairs(windows) do ns.SkinWindow(f) end
    end)
end

---------------------------------------------------------------------------
-- Size
---------------------------------------------------------------------------
local MIN_SCALE, MAX_SCALE = 0.5, 3

local function Clamp(scale)
    return max(MIN_SCALE, min(MAX_SCALE, floor(scale * 100 + 0.5) / 100))
end

local function EllesmereScale()
    if type(EllesmereUI) ~= "table" then return nil end
    local v = type(EllesmereUIDB) == "table" and EllesmereUIDB.panelScale
    if type(v) == "number" and v == v and v > 0 then return Clamp(v) end
    return 1
end

function ns.WindowScale() return ns.db.scale or EllesmereScale() or 1 end

-- A window placed against the screen keeps its centre where it was.
local function Rescale(f, scale)
    local old = f:GetScale() or 1
    if old == scale then return end
    local x, y = f:GetCenter()
    local _, rel = f:GetPoint()
    f:SetScale(scale)
    if type(x) == "number" and type(y) == "number" and (rel == nil or rel == UIParent) then
        f:ClearAllPoints()
        f:SetPoint("CENTER", UIParent, "BOTTOMLEFT", x * old / scale, y * old / scale)
    end
end

local function ApplyScale()
    local scale = ns.WindowScale()
    for _, f in ipairs(windows) do Rescale(f, scale) end
end

local hookedEllesmere
local function HookEllesmere()
    if hookedEllesmere or type(EllesmereUI) ~= "table" or type(EllesmereUI.SetPanelScale) ~= "function" then return end
    hookedEllesmere = true
    pcall(hooksecurefunc, EllesmereUI, "SetPanelScale", function()
        if ns.db.scale == nil then ApplyScale() end
    end)
end

ns.Command("scale", function(text)
    local pct = tonumber((text:gsub("%%", "")))
    if text:lower() == "default" then
        ns.db.scale = nil
        ApplyScale()
    elseif pct then
        ns.db.scale = Clamp(pct / 100)
        ApplyScale()
    end
    ns.Say(L["Window size: %d%%."]:format(floor(ns.WindowScale() * 100 + 0.5)))
end, L["[50-300|default]: the size of our windows, in %"])

---------------------------------------------------------------------------
-- Gamepad UI
---------------------------------------------------------------------------
function ns.GamepadUI()
    local style, types = C_InputInterfaceStyle, Enum and Enum.InputDeviceInterfaceType
    if not (style and style.GetCurrentStyle and types and types.Gamepad) then return false end
    return style.GetCurrentStyle() == types.Gamepad
end

local function Manager()
    local mode = _G.GamepadMode
    return type(mode) == "table" and mode.FrameControlsManager or nil
end

local function Report(ok, err)
    if not ok and geterrorhandler then geterrorhandler()(err) end
end

local function Shown(self)
    local fcm = Manager()
    if not (fcm and fcm.FrameShown and ns.GamepadUI()) or (InCombatLockdown and InCombatLockdown()) then return end
    self.gamepadTracked = true
    Report(pcall(fcm.FrameShown, fcm, self))
end

local function Hidden(self)
    if not self.gamepadTracked then return end
    self.gamepadTracked = nil
    local fcm = Manager()
    if fcm and fcm.FrameHidden then Report(pcall(fcm.FrameHidden, fcm, self)) end
end

---------------------------------------------------------------------------
-- Building blocks
---------------------------------------------------------------------------
-- A movable window with a title and a close button; Escape and the Gamepad UI's B close it.
-- Starts hidden. Set its OnShow/OnHide with HookScript.
function ns.Window(name, title, width, height)
    local ok, f = pcall(CreateFrame, "Frame", name, UIParent, "BasicFrameTemplateWithInset")
    if not ok then f = CreateFrame("Frame", name, UIParent, "BackdropTemplate") end
    f:SetSize(width, height)
    f:SetPoint("CENTER")
    f:SetFrameStrata("DIALOG")
    f:SetToplevel(true)
    f:SetMovable(true)
    f:EnableMouse(true)
    f:RegisterForDrag("LeftButton")
    f:SetScript("OnDragStart", f.StartMoving)
    f:SetScript("OnDragStop", f.StopMovingOrSizing)
    f:SetClampedToScreen(true)
    f.title = f.TitleText or f:CreateFontString(nil, "OVERLAY", "GameFontNormal")
    if not f.TitleText then f.title:SetPoint("TOP", 0, -6) end
    f.title:SetText(title)
    if UISpecialFrames then UISpecialFrames[#UISpecialFrames + 1] = name end
    f:Hide()
    f.SmartNavigationCloseHandler = function(self)
        self:Hide()
        return true
    end
    f:HookScript("OnShow", function(self)
        self:Raise()
        HookEllesmere()
        local scale = ns.WindowScale()
        if self:GetScale() ~= scale then Rescale(self, scale) end
        Shown(self)
    end)
    f:HookScript("OnHide", Hidden)
    f:SetScale(ns.WindowScale())
    windows[#windows + 1] = f
    ns.SkinWindow(f)
    return f
end

function ns.Button(parent, text, width, onClick)
    local b = CreateFrame("Button", nil, parent, "UIPanelButtonTemplate")
    b:SetSize(width or 100, 22)
    b:SetText(text)
    b:SetScript("OnClick", onClick)
    ns.SkinButton(b)
    return b
end

function ns.Label(parent, template)
    local fs = parent:CreateFontString(nil, "OVERLAY", template or "GameFontHighlight")
    fs:SetJustifyH("LEFT")
    ns.SkinText(fs)
    return fs
end

-- A scrolling, read-only text box for copying: what it shows is put back if typed over,
-- and it's selected whenever it gets focus. Returns the box; box:Fill(text) sets it.
function ns.CopyBox(parent, name, width)
    local okScroll, s = pcall(CreateFrame, "ScrollFrame", name .. "Scroll", parent, "UIPanelScrollFrameTemplate")
    if not okScroll then s = CreateFrame("ScrollFrame", name .. "Scroll", parent) end
    local b = CreateFrame("EditBox", name, s)
    b:SetMultiLine(true)
    b:SetAutoFocus(false)
    b:SetFontObject("ChatFontNormal")
    b:SetWidth(width)
    b:SetScript("OnTextChanged", function(self, userInput)
        if userInput and self.text then
            self:SetText(self.text)
            self:HighlightText()
        end
    end)
    b:SetScript("OnEditFocusGained", function(self) self:HighlightText() end)
    b:SetScript("OnEscapePressed", function() parent:Hide() end)
    s:SetScrollChild(b)
    s:EnableMouse(true)
    s:SetScript("OnMouseDown", function() b:SetFocus() end)
    b.scroll = s
    function b:Fill(text)
        self.text = text
        self:SetText(text)
        self:SetFocus()
        self:HighlightText()
        if s.SetVerticalScroll then s:SetVerticalScroll(0) end
    end
    return b
end
