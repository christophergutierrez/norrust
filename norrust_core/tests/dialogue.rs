//! Integration tests for the dialogue system FFI.

use std::ffi::CString;
use std::path::PathBuf;

use norrust_core::ffi::*;

fn project_root() -> PathBuf {
    let manifest = std::env::var("CARGO_MANIFEST_DIR").unwrap();
    PathBuf::from(manifest).parent().unwrap().to_path_buf()
}

unsafe fn c(s: &str) -> CString {
    CString::new(s).unwrap()
}

unsafe fn ffi_string(ptr: *mut std::ffi::c_char) -> String {
    if ptr.is_null() {
        return String::new();
    }
    let s = std::ffi::CStr::from_ptr(ptr).to_string_lossy().into_owned();
    norrust_free_string(ptr);
    s
}

#[test]
fn test_dialogue_ffi_round_trip() {
    unsafe {
        let engine = norrust_new();

        // Load dialogue
        let dialogue_path = c(&project_root().join("scenarios/crossing_dialogue.toml").to_string_lossy());
        assert_eq!(norrust_load_dialogue(engine, dialogue_path.as_ptr()), 1);

        // Query scenario_start — should match the intro entry
        let trigger = c("scenario_start");
        let json = ffi_string(norrust_get_dialogue(engine, trigger.as_ptr(), 1, 0));
        assert!(json.starts_with('['), "should return JSON array");
        assert!(json.contains("crossing_intro"), "should contain intro entry id");
        assert!(json.contains("river crossing"), "should contain intro text");

        // Query turn_start at turn 3 — should match scouts entry
        let trigger = c("turn_start");
        let json = ffi_string(norrust_get_dialogue(engine, trigger.as_ptr(), 3, 0));
        assert!(json.contains("crossing_scouts"), "should contain scouts entry");

        norrust_free(engine);
    }
}

#[test]
fn test_dialogue_ffi_one_shot() {
    unsafe {
        let engine = norrust_new();

        let dialogue_path = c(&project_root().join("scenarios/crossing_dialogue.toml").to_string_lossy());
        assert_eq!(norrust_load_dialogue(engine, dialogue_path.as_ptr()), 1);

        // First call returns entry
        let trigger = c("scenario_start");
        let json1 = ffi_string(norrust_get_dialogue(engine, trigger.as_ptr(), 1, 0));
        assert!(json1.contains("crossing_intro"), "first call should return entry");

        // Second call returns empty array (one-shot)
        let json2 = ffi_string(norrust_get_dialogue(engine, trigger.as_ptr(), 1, 0));
        assert_eq!(json2, "[]", "second call should return empty (one-shot)");

        norrust_free(engine);
    }
}

#[test]
fn test_dialogue_ffi_no_dialogue_loaded() {
    unsafe {
        let engine = norrust_new();

        // Query without loading — should return empty array, not crash
        let trigger = c("scenario_start");
        let json = ffi_string(norrust_get_dialogue(engine, trigger.as_ptr(), 1, 0));
        assert_eq!(json, "[]", "no dialogue loaded should return empty array");

        norrust_free(engine);
    }
}
