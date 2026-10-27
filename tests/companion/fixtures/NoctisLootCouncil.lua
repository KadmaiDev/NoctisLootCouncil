
NoctisLootCouncilDB = {
	["encounters"] = {
		[663] = {
			["name"] = "Lucifron",
			["inst"] = 409,
		},
		[664] = {
			["name"] = "Magmadar",
			["inst"] = 409,
		},
	},
	["window"] = {
		["point"] = "CENTER",
		["x"] = -12.5,
		["y"] = 140.25,
		["scale"] = 0.85,
		["shown"] = false,
	},
	["trials"] = {
		"Trial", -- [1]
		"Initiate", -- [2]
	},
	["decisionsAt"] = 1793000000,
	["items"] = {
		[18000] = {
			["seen"] = 1,
			["inst"] = 409,
			["handling"] = "council",
			["note"] = "Warlock priority",
			["from"] = {
				["e663"] = 1,
			},
			["link"] = "|cffa335ee|Hitem:18000::::::::60:::::::|h[Sash of the Unseen]|h|r",
			["last"] = 1793047200,
			["first"] = 1792700000,
			["q"] = 4,
		},
		[16805] = {
			["seen"] = 2,
			["inst"] = 409,
			["from"] = {
				["e663"] = 1,
				["e664"] = 1,
			},
			["link"] = "|cffa335ee|Hitem:16805::::::::60:::::::|h[Felheart Gloves]|h|r",
			["last"] = 1793049000,
			["first"] = 1793047500,
			["q"] = 4,
		},
		[17069] = {
			["seen"] = 0,
			["handling"] = "roll",
			["from"] = {
			},
			["link"] = "item:17069",
			["last"] = 1792900000,
			["first"] = 1792900000,
			["q"] = 4,
		},
	},
	["instances"] = {
		[409] = "Molten Core",
	},
	["me"] = "Kadmai Moonwhisper",
	["drops"] = {
		{
			["id"] = 18000,
			["at"] = 1793047200,
			["src"] = "e663",
			["inst"] = 409,
			["n"] = 1,
		}, -- [1]
		{
			["id"] = 16805,
			["at"] = 1793047500,
			["src"] = "e663",
			["inst"] = 409,
			["n"] = 1,
		}, -- [2]
		{
			["id"] = 16805,
			["at"] = 1793049000,
			["inst"] = 409,
			["n"] = 1,
		}, -- [3]
	},
	["log"] = {
		{
			["id"] = 18000,
			["link"] = "|cffa335ee|Hitem:18000::::::::60:::::::|h[Sash of the Unseen]|h|r",
			["who"] = "Ilsa Marrow",
			["class"] = "WARLOCK",
			["at"] = 1793047300,
			["how"] = "council",
			["note"] = "Warlock priority; \"biggest\" upgrade\\sidegrade for the rest\nsecond line",
			["inst"] = "Molten Core",
			["boss"] = "Lucifron",
			["nms"] = 4,
			["nos"] = 1,
		}, -- [1]
		{
			["id"] = 16805,
			["link"] = "|cffa335ee|Hitem:16805::::::::60:::::::|h[Felheart Gloves]|h|r",
			["who"] = "Mireíle Duskbane",
			["class"] = "WARLOCK",
			["at"] = 1793047600,
			["how"] = "ms",
			["roll"] = 77,
			["note"] = "BIS",
			["inst"] = "Molten Core",
			["boss"] = "Lucifron",
			["nms"] = 4,
			["nos"] = 1,
		}, -- [2]
		{
			["id"] = 16805,
			["link"] = "|cffa335ee|Hitem:16805::::::::60:::::::|h[Felheart Gloves]|h|r",
			["who"] = "Corvin Dusk",
			["at"] = 1793049100,
			["how"] = "os",
			["roll"] = 64,
			["inst"] = "Molten Core",
			["boss"] = "Magmadar",
			["nms"] = 0,
			["nos"] = 1,
		}, -- [3]
	},
	["v"] = 1,
}
NoctisLootCouncilCharDB = nil
