//! Dialogue system: scenario-level narrator text triggered by game events.
//!
//! Dialogue entries are defined in TOML files alongside scenarios. The client
//! queries for pending dialogue given the current trigger, turn, and faction;
//! entries fire once (one-shot) and are tracked by ID.

use std::collections::HashSet;
use std::path::Path;

use serde::{Deserialize, Serialize};

/// A single dialogue entry loaded from a scenario dialogue TOML file.
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct DialogueEntry {
    /// Unique identifier within the file.
    pub id: String,
    /// Trigger type: "scenario_start", "turn_start", "turn_end", "leader_attacked", "hex_entered".
    pub trigger: String,
    /// Which turn this fires on (None = any turn).
    #[serde(default)]
    pub turn: Option<u32>,
    /// Which faction's turn (None = either faction).
    #[serde(default)]
    pub faction: Option<u8>,
    /// Hex column for location-based triggers (None = any hex).
    #[serde(default)]
    pub col: Option<i32>,
    /// Hex row for location-based triggers (None = any hex).
    #[serde(default)]
    pub row: Option<i32>,
    /// Narrator dialogue text.
    pub text: String,
}

/// TOML file wrapper — dialogue files have `[[dialogue]]` entries.
#[derive(Debug, Deserialize)]
struct DialogueFile {
    dialogue: Vec<DialogueEntry>,
}

/// Runtime state for a scenario's dialogue, tracking which entries have fired.
#[derive(Debug)]
pub struct DialogueState {
    entries: Vec<DialogueEntry>,
    fired: HashSet<String>,
}

impl DialogueState {
    /// Load dialogue entries from a TOML file.
    pub fn load(path: &Path) -> Result<Self, String> {
        let content = std::fs::read_to_string(path)
            .map_err(|e| format!("Failed to read dialogue file: {}", e))?;
        let file: DialogueFile = toml::from_str(&content)
            .map_err(|e| format!("Failed to parse dialogue TOML: {}", e))?;
        Ok(Self {
            entries: file.dialogue,
            fired: HashSet::new(),
        })
    }

    /// Return matching unfired entries for the given trigger, turn, faction, and optional hex.
    /// Matched entries are marked as fired (one-shot semantics).
    pub fn get_pending(
        &mut self,
        trigger: &str,
        turn: u32,
        faction: u8,
        col: Option<i32>,
        row: Option<i32>,
    ) -> Vec<&DialogueEntry> {
        // Collect matching IDs first to avoid borrow issues
        let matching_ids: Vec<String> = self
            .entries
            .iter()
            .filter(|e| {
                e.trigger == trigger
                    && (e.turn.is_none() || e.turn == Some(turn))
                    && (e.faction.is_none() || e.faction == Some(faction))
                    && (e.col.is_none() || e.col == col)
                    && (e.row.is_none() || e.row == row)
                    && !self.fired.contains(&e.id)
            })
            .map(|e| e.id.clone())
            .collect();

        // Mark as fired
        for id in &matching_ids {
            self.fired.insert(id.clone());
        }

        // Return references to matching entries
        self.entries
            .iter()
            .filter(|e| matching_ids.contains(&e.id))
            .collect()
    }

    /// Clear fired state (for scenario restart).
    pub fn reset(&mut self) {
        self.fired.clear();
    }

    /// Return the set of fired dialogue IDs (for save serialization).
    pub fn fired_ids(&self) -> Vec<&String> {
        self.fired.iter().collect()
    }

    /// Mark a dialogue entry as fired by ID (for save restoration).
    pub fn mark_fired(&mut self, id: &str) {
        self.fired.insert(id.to_string());
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_dialogue_path() -> std::path::PathBuf {
        std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .join("scenarios/crossing/dialogue.toml")
    }

    #[test]
    fn test_load_dialogue() {
        let state = DialogueState::load(&test_dialogue_path())
            .expect("should load crossing_dialogue.toml");
        assert!(
            state.entries.len() >= 3,
            "expected at least 3 entries, got {}",
            state.entries.len()
        );
        // Verify first entry has required fields
        let first = &state.entries[0];
        assert!(!first.id.is_empty());
        assert!(!first.trigger.is_empty());
        assert!(!first.text.is_empty());
    }

    #[test]
    fn test_get_pending_filters() {
        let mut state = DialogueState::load(&test_dialogue_path()).unwrap();

        // scenario_start should match on any turn
        let results = state.get_pending("scenario_start", 1, 0, None, None);
        assert!(
            !results.is_empty(),
            "scenario_start should match"
        );
        for r in &results {
            assert_eq!(r.trigger, "scenario_start");
        }

        // Reset so we can test turn_start
        state.reset();

        // turn_start at turn 3 should match
        let results = state.get_pending("turn_start", 3, 0, None, None);
        let has_turn_3 = results.iter().any(|e| e.turn == Some(3));
        assert!(has_turn_3, "turn_start at turn 3 should match");

        // turn_start at turn 99 should not match turn-specific entries
        state.reset();
        let results = state.get_pending("turn_start", 99, 0, None, None);
        let has_turn_specific = results.iter().any(|e| e.turn.is_some());
        assert!(!has_turn_specific, "turn 99 should not match turn-specific entries");
    }

    #[test]
    fn test_one_shot() {
        let mut state = DialogueState::load(&test_dialogue_path()).unwrap();

        let first = state.get_pending("scenario_start", 1, 0, None, None);
        assert!(!first.is_empty(), "first call should return entries");

        let second = state.get_pending("scenario_start", 1, 0, None, None);
        assert!(second.is_empty(), "second call should return empty (one-shot)");
    }

    #[test]
    fn test_reset() {
        let mut state = DialogueState::load(&test_dialogue_path()).unwrap();

        let _ = state.get_pending("scenario_start", 1, 0, None, None);
        state.reset();

        let after_reset = state.get_pending("scenario_start", 1, 0, None, None);
        assert!(!after_reset.is_empty(), "after reset, entries should fire again");
    }

    #[test]
    fn test_hex_entry_filter() {
        let mut state = DialogueState::load(&test_dialogue_path()).unwrap();

        // hex_entered with matching col/row should return the bridge entry
        let results = state.get_pending("hex_entered", 1, 0, Some(8), Some(4));
        assert!(!results.is_empty(), "hex_entered at (8,4) should match bridge entry");
        assert!(results.iter().any(|e| e.id == "crossing_bridge"));

        // One-shot: second call should return empty
        let results2 = state.get_pending("hex_entered", 1, 0, Some(8), Some(4));
        assert!(results2.is_empty(), "one-shot: second call should be empty");

        // Wrong hex should not match
        state.reset();
        let results3 = state.get_pending("hex_entered", 1, 0, Some(0), Some(0));
        assert!(results3.is_empty(), "wrong hex should not match");
    }

    #[test]
    fn test_leader_attacked_trigger() {
        let mut state = DialogueState::load(&test_dialogue_path()).unwrap();

        // leader_attacked should match without col/row
        let results = state.get_pending("leader_attacked", 1, 0, None, None);
        assert!(!results.is_empty(), "leader_attacked should match");
        assert!(results.iter().any(|e| e.id == "crossing_leader_first"));

        // One-shot
        let results2 = state.get_pending("leader_attacked", 1, 0, None, None);
        assert!(results2.is_empty(), "one-shot: second call should be empty");
    }
}
