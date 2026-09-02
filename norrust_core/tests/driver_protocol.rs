use std::io::Write;
use std::process::{Command, Stdio};

use serde_json::Value;

fn run_driver(args: &[&str], input: &str) -> Vec<Value> {
    let mut child = Command::new(env!("CARGO_BIN_EXE_greedy_driver"))
        .args(args)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()
        .expect("start greedy driver");
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
