//! Generic TOML registry loader for game data definitions.

use crate::schema::{FactionDef, RecruitGroup, TerrainDef, UnitDef};
use serde::de::DeserializeOwned;
use std::collections::HashMap;
use std::path::Path;

#[derive(Debug, thiserror::Error)]
pub enum RegistryError {
    #[error("IO error reading {path}: {source}")]
    Io {
        path: String,
        #[source]
        source: std::io::Error,
    },
    #[error("TOML parse error in {path}: {source}")]
    Toml {
        path: String,
        #[source]
        source: toml::de::Error,
    },
}

/// Trait for types that have a string ID field, enabling generic registry loading.
pub trait IdField {
    fn id(&self) -> &str;
}

impl IdField for UnitDef {
    fn id(&self) -> &str {
        &self.id
    }
}

impl IdField for TerrainDef {
    fn id(&self) -> &str {
        &self.id
    }
}

impl IdField for RecruitGroup {
    fn id(&self) -> &str { &self.id }
}

impl IdField for FactionDef {
    fn id(&self) -> &str { &self.id }
}

/// Generic registry that loads and stores TOML-defined game data by ID.
pub struct Registry<T> {
    items: HashMap<String, T>,
}

impl<T> Registry<T>
where
    T: DeserializeOwned + IdField,
{
    /// Load all `.toml` files from `dir` into a Registry keyed by each item's `id` field.
    /// Scans subdirectories recursively for `<dirname>.toml` files at any depth.
    pub fn load_from_dir(dir: &Path) -> Result<Self, RegistryError> {
        let mut items = HashMap::new();
        Self::scan_dir(dir, true, &mut items)?;
        Ok(Registry { items })
    }

    /// Recursively scan a directory for TOML definitions.
    /// When `load_flat` is true, also loads flat `.toml` files (only at the top-level call).
    fn scan_dir(dir: &Path, load_flat: bool, items: &mut HashMap<String, T>) -> Result<(), RegistryError> {
        let entries = std::fs::read_dir(dir).map_err(|e| RegistryError::Io {
            path: dir.display().to_string(),
            source: e,
        })?;

        for entry in entries {
            let entry = entry.map_err(|e| RegistryError::Io {
                path: dir.display().to_string(),
                source: e,
            })?;

            let path = entry.path();

            // Flat .toml file (only at top level)
            if load_flat && path.extension().and_then(|e| e.to_str()) == Some("toml") {
                let content = std::fs::read_to_string(&path).map_err(|e| RegistryError::Io {
                    path: path.display().to_string(),
                    source: e,
                })?;
                let item: T = toml::from_str(&content).map_err(|e| RegistryError::Toml {
                    path: path.display().to_string(),
                    source: e,
                })?;
                items.insert(item.id().to_owned(), item);
                continue;
            }

            // Subdirectory: look for <dirname>.toml inside, then recurse
            if path.is_dir() {
                if let Some(dir_name) = path.file_name().and_then(|n| n.to_str()) {
                    let toml_path = path.join(format!("{}.toml", dir_name));
                    if toml_path.exists() {
                        let content = std::fs::read_to_string(&toml_path).map_err(|e| RegistryError::Io {
                            path: toml_path.display().to_string(),
                            source: e,
                        })?;
                        let item: T = toml::from_str(&content).map_err(|e| RegistryError::Toml {
                            path: toml_path.display().to_string(),
                            source: e,
                        })?;
                        items.insert(item.id().to_owned(), item);
                    }
                }
                // Recurse into subdirectory (never load flat TOMLs in subdirs)
                Self::scan_dir(&path, false, items)?;
            }
        }

        Ok(())
    }

    /// Look up an entry by its ID. Returns `None` if not found.
    pub fn get(&self, id: &str) -> Option<&T> {
        self.items.get(id)
    }

    /// Return an iterator over all loaded entries.
    pub fn all(&self) -> impl Iterator<Item = &T> {
        self.items.values()
    }

    /// Return the number of loaded entries.
    pub fn len(&self) -> usize {
        self.items.len()
    }

    /// Returns `true` if the registry contains no entries.
    pub fn is_empty(&self) -> bool {
        self.items.is_empty()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::schema::{FactionDef, RecruitGroup, TerrainDef, UnitDef};
    use std::path::PathBuf;

    fn data_dir() -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .expect("norrust_core has a parent dir")
            .join("data")
    }

    #[test]
    fn test_unit_registry_loads() {
        let dir = data_dir().join("units");
        let registry: Registry<UnitDef> = Registry::load_from_dir(&dir).unwrap();
        assert!(registry.len() >= 4, "expected at least 4 units, got {}", registry.len());

        let fighter = registry.get("fighter").expect("fighter not found");
        assert_eq!(fighter.max_hp, 30);
        assert_eq!(fighter.movement, 5);
        assert_eq!(fighter.attacks[0].damage, 7);
        assert_eq!(fighter.attacks[0].strikes, 3);
        assert_eq!(fighter.level, 1);
        assert_eq!(fighter.experience, 40);
        assert_eq!(fighter.advances_to, vec!["hero"]);

        let archer = registry.get("archer").expect("archer not found");
        assert_eq!(archer.max_hp, 25);
        assert_eq!(archer.attacks[0].damage, 5);
        assert_eq!(archer.attacks[0].strikes, 4);

        let hero = registry.get("hero").expect("hero not found");
        assert_eq!(hero.max_hp, 45);
        assert_eq!(hero.level, 2);

        let ranger = registry.get("ranger").expect("ranger not found");
        assert_eq!(ranger.max_hp, 38);
        assert_eq!(ranger.level, 2);
    }

    #[test]
    fn test_terrain_registry_loads() {
        let dir = data_dir().join("terrain");
        let registry: Registry<TerrainDef> = Registry::load_from_dir(&dir).unwrap();
        assert!(registry.len() >= 3, "expected at least 3 terrain types, got {}", registry.len());

        let flat = registry.get("flat").expect("flat not found");
        assert_eq!(flat.default_defense, 60);
        assert_eq!(flat.default_movement_cost, 1);
        assert_eq!(flat.color, "#4a7c4e", "flat terrain color must match TOML value");

        let forest = registry.get("forest").expect("forest not found");
        assert_eq!(forest.default_defense, 60);
        assert_eq!(forest.default_movement_cost, 2);

        let village = registry.get("village").expect("village not found");
        assert_eq!(village.healing, 8);
        assert_eq!(village.default_defense, 40);
    }

    #[test]
    fn test_get_nonexistent_returns_none() {
        let dir = data_dir().join("units");
        let registry: Registry<UnitDef> = Registry::load_from_dir(&dir).unwrap();
        assert!(registry.get("dragon").is_none());
    }

    #[test]
    fn test_recruit_group_registry_loads() {
        let dir = data_dir().join("recruit_groups");
        let registry: Registry<RecruitGroup> = Registry::load_from_dir(&dir).unwrap();
        assert_eq!(registry.len(), 3, "expected 3 recruit groups, got {}", registry.len());

        let elf = registry.get("elf_base").expect("elf_base not found");
        assert!(elf.members.contains(&"Elvish Fighter".to_string()), "elf_base missing Elvish Fighter");
        assert!(elf.members.contains(&"Elvish Archer".to_string()), "elf_base missing Elvish Archer");

        let human = registry.get("human_base").expect("human_base not found");
        assert!(human.members.contains(&"Spearman".to_string()), "human_base missing Spearman");

        let orc = registry.get("orc_base").expect("orc_base not found");
        assert!(orc.members.contains(&"Orcish Grunt".to_string()), "orc_base missing Orcish Grunt");
    }

    #[test]
    fn test_faction_registry_loads() {
        let dir = data_dir().join("factions");
        let registry: Registry<FactionDef> = Registry::load_from_dir(&dir).unwrap();
        assert_eq!(registry.len(), 3, "expected 3 factions, got {}", registry.len());

        let elves = registry.get("elves").expect("elves faction not found");
        assert_eq!(elves.leader_def, "Elvish Captain");
        assert_eq!(elves.recruits, vec!["elf_base"]);

        let loyalists = registry.get("loyalists").expect("loyalists not found");
        assert_eq!(loyalists.leader_def, "Lieutenant");
        assert_eq!(loyalists.recruits, vec!["human_base"]);

        let orcs = registry.get("orcs").expect("orcs not found");
        assert_eq!(orcs.leader_def, "Orcish Warrior");
    }

    #[test]
    fn test_faction_recruit_expansion_and_level_filter() {
        let groups = Registry::<RecruitGroup>::load_from_dir(&data_dir().join("recruit_groups")).unwrap();
        let factions = Registry::<FactionDef>::load_from_dir(&data_dir().join("factions")).unwrap();
        let units = Registry::<UnitDef>::load_from_dir(&data_dir().join("units")).unwrap();

        for faction in factions.all() {
            // Expand recruits
            let mut recruits: Vec<String> = Vec::new();
            for entry in &faction.recruits {
                if let Some(grp) = groups.get(entry) {
                    recruits.extend(grp.members.iter().cloned());
                } else {
                    recruits.push(entry.clone());
                }
            }
            assert!(!recruits.is_empty(), "faction '{}' expanded to empty recruit list", faction.id);

            // Verify leader exists in unit registry
            let leader = units.get(&faction.leader_def)
                .unwrap_or_else(|| panic!("faction '{}' leader '{}' not in unit registry", faction.id, faction.leader_def));
            let max_level = leader.level as i32;

            // All recruits should exist in unit registry
            for recruit_id in &recruits {
                assert!(
                    units.get(recruit_id).is_some(),
                    "faction '{}' recruit '{}' not found in unit registry",
                    faction.id, recruit_id
                );
            }

            // Level-filtered list should be non-empty
            let filtered: Vec<&String> = recruits.iter()
                .filter(|id| units.get(id.as_str()).map(|u| u.level as i32 <= max_level).unwrap_or(true))
                .collect();
            assert!(
                !filtered.is_empty(),
                "faction '{}' has empty recruit list after level filter (max_level={})",
                faction.id, max_level
            );
        }
    }
}
