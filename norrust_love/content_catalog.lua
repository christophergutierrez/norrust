-- Tracked menu content. Keep ordering and display names stable for saves/docs.
return {
    scenarios = {
        {name = "Quick Play", board = "contested/board.toml", units = "contested/units.toml", preset_units = false},
        {name = "Night Battle", board = "night_orcs/board.toml", units = "night_orcs/units.toml", preset_units = false},
        {name = "Big Battle 6", board = "big_battle_6/board.toml", units = "big_battle_6/units.toml", preset_units = false, starting_gold = 300},
    },
    campaigns = {
        {name = "A Tale of Two Brothers", file = "two_brothers.toml"},
        {name = "The Road to Norrust", file = "tutorial.toml"},
    },
}
