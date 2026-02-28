use crate::schema::{TerrainDef, UnitDef};
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

pub struct Registry<T> {
    items: HashMap<String, T>,
}

impl<T> Registry<T>
where
    T: DeserializeOwned + IdField,
{
    /// Load all `.toml` files from `dir` into a Registry keyed by each item's `id` field.
    pub fn load_from_dir(dir: &Path) -> Result<Self, RegistryError> {
        let mut items = HashMap::new();

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
            if path.extension().and_then(|e| e.to_str()) != Some("toml") {
                continue;
            }

            let content = std::fs::read_to_string(&path).map_err(|e| RegistryError::Io {
                path: path.display().to_string(),
                source: e,
            })?;

            let item: T = toml::from_str(&content).map_err(|e| RegistryError::Toml {
                path: path.display().to_string(),
                source: e,
            })?;

            items.insert(item.id().to_owned(), item);
        }

        Ok(Registry { items })
    }

    pub fn get(&self, id: &str) -> Option<&T> {
        self.items.get(id)
    }

    pub fn all(&self) -> impl Iterator<Item = &T> {
        self.items.values()
    }

    pub fn len(&self) -> usize {
        self.items.len()
    }

    pub fn is_empty(&self) -> bool {
        self.items.is_empty()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::schema::{TerrainDef, UnitDef};
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
        assert_eq!(registry.len(), 2);

        let fighter = registry.get("fighter").expect("fighter not found");
        assert_eq!(fighter.max_hp, 30);
        assert_eq!(fighter.movement, 5);
        assert_eq!(fighter.attacks[0].damage, 7);
        assert_eq!(fighter.attacks[0].strikes, 3);

        let archer = registry.get("archer").expect("archer not found");
        assert_eq!(archer.max_hp, 25);
        assert_eq!(archer.attacks[0].damage, 5);
        assert_eq!(archer.attacks[0].strikes, 4);
    }

    #[test]
    fn test_terrain_registry_loads() {
        let dir = data_dir().join("terrain");
        let registry: Registry<TerrainDef> = Registry::load_from_dir(&dir).unwrap();
        assert_eq!(registry.len(), 2);

        let grass = registry.get("grassland").expect("grassland not found");
        assert_eq!(grass.default_defense, 40);
        assert_eq!(grass.default_movement_cost, 1);

        let forest = registry.get("forest").expect("forest not found");
        assert_eq!(forest.default_defense, 60);
        assert_eq!(forest.default_movement_cost, 2);
    }

    #[test]
    fn test_get_nonexistent_returns_none() {
        let dir = data_dir().join("units");
        let registry: Registry<UnitDef> = Registry::load_from_dir(&dir).unwrap();
        assert!(registry.get("dragon").is_none());
    }
}
