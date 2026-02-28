use crate::loader::Registry;
use crate::schema::{TerrainDef, UnitDef};
use godot::prelude::*;

/// GDExtension entry point — registers all Rust classes with Redot.
struct NorRustExtension;

#[gdextension]
unsafe impl ExtensionLibrary for NorRustExtension {}

/// The primary Rust node exposed to Redot.
/// Instantiate via NorRustCore.new() in GDScript.
#[derive(GodotClass)]
#[class(base=Node)]
pub struct NorRustCore {
    base: Base<Node>,
    units: Option<Registry<UnitDef>>,
    terrain: Option<Registry<TerrainDef>>,
}

#[godot_api]
impl INode for NorRustCore {
    fn init(base: Base<Node>) -> Self {
        Self {
            base,
            units: None,
            terrain: None,
        }
    }
}

#[godot_api]
impl NorRustCore {
    /// Returns the norrust_core library version string.
    #[func]
    fn get_core_version(&self) -> GString {
        "0.1.0".into()
    }

    /// Load all game data from `data_path/units/` and `data_path/terrain/`.
    /// Returns true on success, false on any IO or parse error.
    /// From GDScript: pass `ProjectSettings.globalize_path("res://") + "/../data"`
    #[func]
    fn load_data(&mut self, data_path: GString) -> bool {
        use std::path::PathBuf;
        let base = PathBuf::from(data_path.to_string());

        match Registry::<UnitDef>::load_from_dir(&base.join("units")) {
            Ok(registry) => self.units = Some(registry),
            Err(e) => {
                godot_error!("load_data: failed to load units: {}", e);
                return false;
            }
        }

        match Registry::<TerrainDef>::load_from_dir(&base.join("terrain")) {
            Ok(registry) => self.terrain = Some(registry),
            Err(e) => {
                godot_error!("load_data: failed to load terrain: {}", e);
                return false;
            }
        }

        godot_print!(
            "load_data: loaded {} units, {} terrain types",
            self.units.as_ref().map(|r| r.len()).unwrap_or(0),
            self.terrain.as_ref().map(|r| r.len()).unwrap_or(0),
        );
        true
    }

    /// Returns max_hp for the unit, or -1 if not found or data not loaded.
    #[func]
    fn get_unit_max_hp(&self, unit_id: GString) -> i32 {
        self.units
            .as_ref()
            .and_then(|r| r.get(&unit_id.to_string()))
            .map(|u| u.max_hp as i32)
            .unwrap_or(-1)
    }
}
