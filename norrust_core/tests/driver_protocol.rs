use std::io::Write;
use std::process::{Command, Stdio};

use serde_json::Value;

fn run_driver(args: &[&str], input: &str) -> Vec<Value> {
    run_driver_with_env(args, input, &[])
}

fn run_driver_with_env(args: &[&str], input: &str, env: &[(&str, &str)]) -> Vec<Value> {
    let mut command = Command::new(env!("CARGO_BIN_EXE_greedy_driver"));
    command
        .args(args)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped());
    for (key, value) in env {
        command.env(key, value);
    }
    let mut child = command.spawn().expect("start greedy driver");
    child
        .stdin
        .take()
        .expect("driver stdin")
        .write_all(input.as_bytes())
        .expect("write driver input");
    let output = child.wait_with_output().expect("wait for driver");
    assert!(
        output.status.success(),
        "driver failed: {:?}",
        output.status
    );
    String::from_utf8(output.stdout)
        .expect("driver output is utf8")
        .lines()
        .map(|line| serde_json::from_str(line).expect("every driver line is JSON"))
        .collect()
}

#[test]
fn malformed_requests_get_one_typed_status_each() {
    let lines = run_driver(
        &[
            "--scenario",
            "big_battle_6",
            "--faction0",
            "undead",
            "--faction1",
            "undead",
            "--max-turns",
            "1",
        ],
        "not json\n{\"action\":\"Query\",\"what\":\"nope\"}\n{\"action\":\"Query\",\"what\":\"legal_moves\"}\n",
    );
    assert_eq!(lines[0]["type"], "protocol");
    let statuses: Vec<&Value> = lines
        .iter()
        .filter(|line| line["type"] == "status")
        .collect();
    assert_eq!(statuses.len(), 3);
    assert!(statuses.iter().all(|line| line["ok"] == false));
    assert_eq!(statuses[0]["code"], "parse");
    assert_eq!(statuses[1]["code"], "unknown_query");
    assert_eq!(statuses[2]["code"], "UnitNotFound");
}

#[test]
fn invalid_setup_is_reported_as_game_end() {
    let lines = run_driver(
        &[
            "--scenario",
            "big_battle_6",
            "--faction0",
            "does_not_exist",
            "--faction1",
            "undead",
        ],
        "",
    );
    assert_eq!(lines[0]["type"], "protocol");
    assert_eq!(lines[1]["type"], "game_end");
    assert_eq!(lines[1]["reason"], "setup_error");
    assert_eq!(lines[1]["code"], "invalid_setup");
}

#[test]
fn model_end_turn_runs_greedy_recruit_and_action_then_returns_to_model_side() {
    let lines = run_driver(
        &[
            "--scenario",
            "big_battle_6",
            "--faction0",
            "undead",
            "--faction1",
            "undead",
            "--gold",
            "100",
            "--max-turns",
            "4",
        ],
        "{\"action\":\"EndTurn\"}\n",
    );
    assert_eq!(lines[0]["type"], "protocol");
    let boundaries: Vec<&Value> = lines
        .iter()
        .filter(|line| line["type"] == "state")
        .collect();
    assert_eq!(boundaries.len(), 2);
    assert_eq!(boundaries[0]["active_faction"], 0);
    assert_eq!(boundaries[1]["active_faction"], 0);
    assert!(lines.iter().any(|line| {
        line["type"] == "events"
            && line["source"] == "greedy"
            && line["events"].as_array().is_some_and(|events| {
                events.iter().any(|event| event["kind"] == "recruit")
                    && events
                        .iter()
                        .any(|event| event["kind"] == "move" || event["kind"] == "attack")
            })
    }));
}

#[test]
fn model_rejects_foreign_unit_reference_at_model_boundary() {
    let lines = run_driver(
        &[
            "--scenario",
            "big_battle_6",
            "--faction0",
            "undead",
            "--faction1",
            "undead",
            "--llm-side",
            "1",
            "--max-turns",
            "4",
        ],
        "{\"action\":\"Move\",\"unit_id\":1,\"col\":1,\"row\":1}\n",
    );
    assert_eq!(lines[0]["type"], "protocol");
    let boundary = lines.iter().find(|line| line["type"] == "state").unwrap();
    assert_eq!(boundary["active_faction"], 1);
    let status = lines.iter().find(|line| line["type"] == "status").unwrap();
    assert_eq!(status["ok"], false);
    assert_eq!(status["code"], "unauthorized_unit");
    assert!(status["results"].is_null());
    assert_eq!(
        lines.iter().filter(|line| line["type"] == "state").count(),
        1
    );
}

fn recruit_options_query(args: &[&str]) -> Value {
    let lines = run_driver(
        args,
        "{\"action\":\"Query\",\"what\":\"recruit_options\"}\n",
    );
    lines
        .into_iter()
        .find(|line| line["what"] == "recruit_options")
        .expect("recruit_options response")
}

#[test]
fn recruit_options_reports_canonical_active_faction_placements_and_enabled_batch_macro() {
    let response = recruit_options_query(&[
        "--scenario",
        "big_battle_6",
        "--faction0",
        "undead",
        "--faction1",
        "undead",
    ]);
    assert_eq!(response["body"]["faction_id"], "undead");
    assert_eq!(response["body"]["batch_macro_enabled"], true);
    let placements = response["body"]["placement_hexes"].as_array().unwrap();
    let coordinates: Vec<(i64, i64)> = placements
        .iter()
        .map(|hex| (hex["col"].as_i64().unwrap(), hex["row"].as_i64().unwrap()))
        .collect();
    let mut unique = coordinates.clone();
    unique.sort_unstable_by_key(|(col, row)| (*row, *col));
    unique.dedup();
    assert_eq!(coordinates, unique);
    assert_eq!(
        coordinates,
        vec![(2, 6), (3, 6), (1, 7), (3, 7), (2, 8), (3, 8)]
    );
}

#[test]
fn recruit_options_reports_disabled_batch_macro() {
    let response = recruit_options_query(&[
        "--scenario",
        "big_battle_6",
        "--faction0",
        "undead",
        "--faction1",
        "undead",
        "--disable-recruit-batch",
    ]);
    assert_eq!(response["body"]["batch_macro_enabled"], false);
}

#[test]
fn greedy_failure_is_typed_terminal_without_boundary_events_or_accounting_mutation() {
    let lines = run_driver_with_env(
        &[
            "--scenario",
            "big_battle_6",
            "--faction0",
            "undead",
            "--faction1",
            "undead",
            "--max-turns",
            "4",
        ],
        "{\"action\":\"EndTurn\"}\n",
        &[("NORRUST_TEST_GREEDY_FAILURE", "planner")],
    );
    assert_eq!(lines[0]["type"], "protocol");
    assert!(lines.iter().any(|line| line["type"] == "state"));
    let terminal = lines
        .iter()
        .find(|line| line["reason"] == "infrastructure_failure")
        .unwrap();
    assert_eq!(terminal["code"], "greedy_turn_failed");
    assert_eq!(terminal["message"], "greedy opponent turn failed");
    assert_eq!(terminal["turns"], 1);
    assert_eq!(terminal["side_turns"], 1);
    let terminal_index = lines
        .iter()
        .position(|line| line["reason"] == "infrastructure_failure")
        .unwrap();
    assert!(!lines[..terminal_index]
        .iter()
        .any(|line| { line["type"] == "events" && line["source"] == "greedy" }));
    assert!(!lines
        .iter()
        .skip_while(|line| line["type"] != "game_end")
        .skip(1)
        .any(|line| line["type"] == "state"));
    assert!(!lines
        .iter()
        .skip_while(|line| line["type"] != "game_end")
        .skip(1)
        .any(|line| line["type"] == "events"));
    assert!(!lines.iter().any(|line| {
        line["reason"] == "draw" || line["reason"] == "winner" || line["reason"] == "max_turns"
    }));
}

#[test]
fn initial_greedy_failure_for_llm_side_one_is_typed_terminal() {
    let lines = run_driver_with_env(
        &[
            "--scenario",
            "big_battle_6",
            "--faction0",
            "undead",
            "--faction1",
            "undead",
            "--llm-side",
            "1",
            "--max-turns",
            "4",
        ],
        "",
        &[("NORRUST_TEST_GREEDY_FAILURE", "prepare")],
    );
    assert_eq!(lines[0]["type"], "protocol");
    let terminal = lines
        .iter()
        .find(|line| line["reason"] == "infrastructure_failure")
        .unwrap();
    assert_eq!(terminal["type"], "game_end");
    assert_eq!(terminal["code"], "greedy_turn_failed");
    assert_eq!(terminal["message"], "greedy opponent turn failed");
    assert_eq!(terminal["turns"], 1);
    assert_eq!(terminal["side_turns"], 0);
}

#[test]
fn max_turns_caps_successful_side_turns() {
    let lines = run_driver(
        &[
            "--scenario",
            "big_battle_6",
            "--faction0",
            "undead",
            "--faction1",
            "undead",
            "--max-turns",
            "1",
        ],
        "{\"action\":\"EndTurn\"}\n",
    );
    let terminal = lines
        .iter()
        .find(|line| line["reason"] == "max_turns")
        .unwrap();
    assert_eq!(terminal["side_turns"], 1);
    assert!(!lines.iter().any(|line| line["source"] == "greedy"));
}
