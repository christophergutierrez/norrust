use std::env;
use std::fs;
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
fn resignation_concedes_either_side_without_advancing_or_running_opponent() {
    for side in ["0", "1"] {
        let lines = run_driver(
            &["--scenario", "big_battle_6", "--llm-side", side, "--max-turns", "50"],
            "[{\"action\":\"Resign\"}]\n[{\"action\":\"EndTurn\"}]\n",
        );
        let boundary = lines.iter().rposition(|line| line["type"] == "state").unwrap();
        let after = &lines[boundary + 1..];
        assert_eq!(after.len(), 2, "only acknowledgement and terminal may follow resignation");
        assert_eq!(after[0]["ok"], true);
        let terminal = &after[1];
        assert_eq!(terminal["type"], "game_end");
        assert_eq!(terminal["reason"], "resignation");
        let side: u8 = side.parse().unwrap();
        assert_eq!(terminal["winner"], 1 - side);
        assert_eq!(terminal["resigned_side"], side);
        assert_eq!(terminal["side_turns"], side);
        assert_eq!(terminal["state_revision"], lines[boundary]["state_revision"]);
    }
}

#[test]
fn malformed_resignation_never_commits_other_orders() {
    let lines = run_driver(
        &["--scenario", "big_battle_6", "--max-turns", "50"],
        r#"[{"action":"Resign","side":1}]
[{"action":"RecruitBatch","def_id":"Skeleton","count":1},{"action":"Resign"}]
[{"action":"Resign"},{"action":"EndTurn"}]
[{"action":"Resign"},{"action":"Resign"}]
[{"action":"Resign"}]
"#,
    );
    let statuses: Vec<_> = lines.iter().filter(|line| line["type"] == "status").collect();
    assert_eq!(statuses.len(), 5);
    assert!(statuses[..4].iter().all(|line| line["ok"] == false));
    assert_eq!(statuses[4]["ok"], true);
    assert!(!lines.iter().any(|line| line["type"] == "events"));
    assert_eq!(lines.last().unwrap()["state_revision"], 0);
    assert_eq!(lines.last().unwrap()["side_turns"], 0);
}

#[test]
fn resignation_validation_is_read_only_and_tactical_previews_reject_it() {
    let lines = run_driver(
        &["--scenario", "big_battle_6", "--max-turns", "50", "--incremental-turns"],
        r#"{"action":"Query","what":"validate_batch","state_revision":0,"orders":[{"action":"Resign"}]}
{"action":"Query","what":"preview_batch","state_revision":0,"phase":"final","candidates":[[{"action":"Resign"}]]}
{"action":"Query","what":"preview_batch","state_revision":0,"phase":"partial","candidates":[[{"action":"Resign"}]]}
[{"action":"Resign"}]
"#,
    );
    let statuses: Vec<_> = lines.iter().filter(|line| line["type"] == "status").collect();
    assert_eq!(statuses.len(), 4);
    assert_eq!(statuses[0]["body"]["valid"], true);
    assert_eq!(statuses[1]["ok"], false);
    assert_eq!(statuses[2]["ok"], false);
    assert_eq!(lines.last().unwrap()["reason"], "resignation");
    assert_eq!(lines.last().unwrap()["state_revision"], 0);
    assert!(!lines.iter().any(|line| line["type"] == "events"));
}

#[test]
fn resignation_is_allowed_after_the_partial_batch_limit() {
    let lines = run_driver(
        &["--scenario", "big_battle_6", "--faction0", "undead", "--gold", "300",
          "--max-turns", "50", "--incremental-turns"],
        r#"[{"action":"RecruitBatch","def_id":"Skeleton","count":1}]
[{"action":"RecruitBatch","def_id":"Skeleton","count":1}]
[{"action":"RecruitBatch","def_id":"Skeleton","count":1}]
[{"action":"Resign"}]
"#,
    );
    let states: Vec<_> = lines.iter().filter(|line| line["type"] == "state").collect();
    assert_eq!(states.last().unwrap()["accepted_partial_batches"], 3);
    let terminal = lines.last().unwrap();
    assert_eq!(terminal["reason"], "resignation");
    assert_eq!(terminal["side_turns"], 0);
    assert_eq!(terminal["state_revision"], states.last().unwrap()["state_revision"]);
    for batch in lines.iter().filter(|line| line["type"] == "events") {
        assert!(batch["events"].as_array().unwrap().iter().all(|event| event["kind"] == "recruit"));
    }
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
fn partial_preview_accepts_prefix_and_labels_unavailable_sweep() {
    let lines = run_driver(
        &[
            "--scenario", "big_battle_6", "--faction0", "undead", "--faction1", "undead",
            "--gold", "300", "--max-turns", "1", "--incremental-turns",
        ],
        r#"{"action":"Query","what":"preview_batch","state_revision":0,"phase":"partial","candidates":[[{"action":"RecruitBatch","def_id":"Skeleton","count":1}]]}
{"action":"Query","what":"preview_batch","state_revision":0,"phase":"partial","candidates":[[{"action":"EndTurn"}]]}
"#,
    );
    let statuses: Vec<&Value> = lines.iter().filter(|line| line["type"] == "status").collect();
    assert_eq!(statuses[0]["ok"], true);
    assert_eq!(statuses[0]["body"]["phase"], "partial");
    assert_eq!(statuses[0]["body"]["coverage"]["delegated_sweep"], "unavailable");
    assert_eq!(statuses[1]["ok"], false);
    assert_eq!(statuses[1]["code"], "parse");
}

#[test]
fn final_nonsampling_preview_is_pre_finish_and_does_not_claim_a_sweep() {
    let lines = run_driver(
        &[
            "--scenario", "big_battle_6", "--faction0", "undead", "--faction1", "undead",
            "--gold", "300", "--max-turns", "1", "--incremental-turns",
        ],
        r#"{"action":"Query","what":"preview_batch","state_revision":0,"phase":"final","candidates":[[{"action":"EndTurn"}]]}
"#,
    );
    let status = lines
        .iter()
        .find(|line| line["type"] == "status")
        .expect("preview status");
    assert_eq!(status["ok"], true);
    let body = &status["body"];
    assert_eq!(body["sampling"], false);
    assert_eq!(body["coverage"]["forecast"], "conditional_pre_finish");
    assert_eq!(body["coverage"]["delegated_sweep"], "unavailable");
    assert_eq!(body["coverage"]["post_sweep"], "unavailable");
    assert_eq!(body["candidates"][0]["observation_stage"], "post_prefix_pre_sweep");
    assert_eq!(body["candidates"][0]["post_sweep"], Value::Null);
}

#[test]
fn bounded_preview_reports_isolated_finish_and_opponent_coverage() {
    let lines = run_driver(
        &[
            "--scenario", "big_battle_6", "--faction0", "undead", "--faction1", "undead",
            "--gold", "300", "--max-turns", "1",
        ],
        r#"{"action":"Query","what":"preview_batch","state_revision":0,"phase":"final","mode":"bounded_rollout","candidates":[[{"action":"EndTurn"}]]}
"#,
    );
    let status = lines.iter().find(|line| line["type"] == "status").expect("preview status");
    assert_eq!(status["ok"], true);
    let body = &status["body"];
    assert_eq!(body["sampling"], true);
    assert_eq!(body["coverage"]["post_sweep"], "modeled");
    let candidate = &body["candidates"][0];
    assert_eq!(candidate["observation_stage"], "post_opponent_response");
    assert_eq!(candidate["post_sweep"]["policy"], "driver_greedy_one_response_v1");
    assert_eq!(candidate["post_sweep"]["evaluation_seed"], 0x5eed5eed5eed5eedu64);
    let post_finish = &candidate["post_sweep"]["stages"]["post_finish"];
    assert!(post_finish.is_object());
    assert!(post_finish["units_detail"].is_array());
    assert!(post_finish["villages"].is_array());
    assert!(post_finish["sides"][0]["material_cost"].is_number());
}

#[test]
fn unavailable_target_inspection_is_factual_and_nonfatal() {
    let lines = run_driver(
        &[
            "--scenario", "big_battle_6", "--faction0", "undead", "--faction1", "undead",
            "--gold", "300", "--max-turns", "1",
        ],
        r#"{"action":"Query","what":"inspect_targets","state_revision":0,"unit_ids":[999999]}
"#,
    );
    let status = lines.iter().find(|line| line["type"] == "status").expect("inspection status");
    assert_eq!(status["ok"], true);
    assert_eq!(status["body"]["targets"][0]["available"], false);
    assert_eq!(status["body"]["targets"][0]["reason"], "unit_unavailable");
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
fn done_with_important_moves_matches_implicit_end_turn_behavior() {
    let args = [
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
    ];
    let explicit = run_driver(&args, "{\"action\":\"DoneWithImportantMoves\"}\n");
    let implicit = run_driver(&args, "{\"action\":\"EndTurn\"}\n");

    assert_eq!(explicit[0]["version"], 2);
    let explicit_status = explicit
        .iter()
        .find(|line| line["type"] == "status")
        .unwrap();
    let implicit_status = implicit
        .iter()
        .find(|line| line["type"] == "status")
        .unwrap();
    assert_eq!(explicit_status["finish_kind"], "explicit_done");
    assert_eq!(implicit_status["finish_kind"], "implicit_end_turn");

    let explicit_state = explicit
        .iter()
        .filter(|line| line["type"] == "state")
        .nth(1)
        .unwrap();
    let implicit_state = implicit
        .iter()
        .filter(|line| line["type"] == "state")
        .nth(1)
        .unwrap();
    assert_eq!(explicit_state, implicit_state);

    let explicit_events = explicit
        .iter()
        .find(|line| line["type"] == "events" && line["source"] == "delegated_greedy")
        .unwrap();
    let implicit_events = implicit
        .iter()
        .find(|line| line["type"] == "events" && line["source"] == "delegated_greedy")
        .unwrap();
    assert_eq!(explicit_events["finish_kind"], "explicit_done");
    assert_eq!(implicit_events["finish_kind"], "implicit_end_turn");
    let mut explicit_without_kind = explicit_events.clone();
    let mut implicit_without_kind = implicit_events.clone();
    explicit_without_kind
        .as_object_mut()
        .unwrap()
        .remove("finish_kind");
    implicit_without_kind
        .as_object_mut()
        .unwrap()
        .remove("finish_kind");
    assert_eq!(explicit_without_kind, implicit_without_kind);
}

#[test]
fn done_after_recruit_sweeps_the_new_unit_without_delegated_recruitment() {
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
        "[{\"action\":\"Recruit\",\"def_id\":\"Skeleton\",\"col\":2,\"row\":6},{\"action\":\"DoneWithImportantMoves\"}]\n",
    );
    let status = lines.iter().find(|line| line["type"] == "status").unwrap();
    assert_eq!(status["finish_kind"], "explicit_done");
    assert!(lines.iter().any(|line| {
        line["type"] == "events"
            && line["source"] == "llm"
            && line["events"]
                .as_array()
                .is_some_and(|events| events.iter().any(|event| event["kind"] == "recruit"))
    }));
    assert!(!lines.iter().any(|line| {
        line["type"] == "events"
            && line["source"] == "delegated_greedy"
            && line["events"]
                .as_array()
                .is_some_and(|events| events.iter().any(|event| event["kind"] == "recruit"))
    }));
}

#[test]
fn finish_with_greedy_is_terminal_allowlisted_and_provenanced() {
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
        r#"{"action":"FinishWithGreedy","groups":[{"mode":"greedy","unit_ids":[1]}],"holds":[]}
"#,
    );
    let status = lines
        .iter()
        .find(|line| line["type"] == "status")
        .expect("finish status");
    assert_eq!(status["ok"], true);
    assert_eq!(status["results"][0]["ok"], true);
    assert!(lines.iter().any(|line| {
        line["type"] == "events"
            && line["source"] == "delegated_greedy"
            && line["events"].as_array().is_some_and(|events| {
                events
                    .iter()
                    .all(|event| event["source"] == "delegated_greedy")
                    && events.iter().any(|event| event["kind"] == "end_turn")
            })
    }));
    assert_eq!(
        lines
            .iter()
            .filter(|line| line["type"] == "events" && line["source"] == "delegated_greedy")
            .count(),
        1
    );
}

#[test]
fn finish_with_greedy_accepts_empty_groups_and_keeps_selective_telemetry() {
    let lines = run_driver(
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
        r#"{"action":"FinishWithGreedy","groups":[],"holds":[]}
"#,
    );
    let status = lines.iter().find(|line| line["type"] == "status").unwrap();
    assert_eq!(status["ok"], true);
    assert_eq!(status["finish_kind"], "selective");
    assert!(lines.iter().any(|line| {
        line["type"] == "events"
            && line["source"] == "delegated_greedy"
            && line["finish_kind"] == "selective"
            && line["events"]
                .as_array()
                .is_some_and(|events| events.iter().all(|event| event["kind"] == "end_turn"))
    }));
}

#[test]
fn finish_with_greedy_rejects_duplicate_or_foreign_ids_before_mutation() {
    let lines = run_driver(
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
        r#"{"action":"FinishWithGreedy","groups":[{"mode":"greedy","unit_ids":[1,1]}],"holds":[]}
{"action":"FinishWithGreedy","groups":[{"mode":"greedy","unit_ids":[999]}],"holds":[]}
"#,
    );
    let statuses: Vec<&Value> = lines
        .iter()
        .filter(|line| line["type"] == "status")
        .collect();
    assert_eq!(statuses[0]["code"], "parse");
    assert_eq!(statuses[1]["code"], "unauthorized_unit");
    assert_eq!(
        lines.iter().filter(|line| line["type"] == "state").count(),
        1
    );
}

#[test]
fn incremental_validation_and_submission_share_the_partial_batch_limit() {
    let partial = r#"[{"action":"RecruitBatch","def_id":"Skeleton","count":1}]"#;
    let input = format!("{partial}\n{partial}\n{partial}\n{partial}\n{{\"action\":\"EndTurn\"}}\n");
    let lines = run_driver(
        &[
            "--scenario",
            "big_battle_6",
            "--faction0",
            "undead",
            "--faction1",
            "undead",
            "--gold",
            "300",
            "--max-turns",
            "1",
            "--incremental-turns",
        ],
        &input,
    );
    let statuses: Vec<&Value> = lines
        .iter()
        .filter(|line| line["type"] == "status")
        .collect();
    assert!(statuses.iter().any(|line| line["code"] == "partial_limit"));
    assert!(lines
        .iter()
        .any(|line| line["type"] == "state" && line["turn_boundary"] == "partial"));
    assert!(lines.iter().any(|line| line["type"] == "game_end"));
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

#[test]
fn undead_recruitment_is_roster_gated_and_valid_recruitment_still_works() {
    let rejected = run_driver(
        &[
            "--scenario",
            "big_battle_6",
            "--faction0",
            "undead",
            "--faction1",
            "undead",
            "--gold",
            "100",
        ],
        "[{\"action\":\"Recruit\",\"def_id\":\"Orcish Grunt\",\"col\":2,\"row\":6},{\"action\":\"EndTurn\"}]\n",
    );
    let rejected_status = rejected
        .iter()
        .find(|line| line["type"] == "status")
        .unwrap();
    assert_eq!(rejected_status["results"][0]["ok"], false);
    assert_eq!(rejected_status["results"][0]["code"], "NotInRecruitList");

    let accepted = run_driver(
        &[
            "--scenario",
            "big_battle_6",
            "--faction0",
            "undead",
            "--faction1",
            "undead",
            "--gold",
            "100",
        ],
        "[{\"action\":\"Recruit\",\"def_id\":\"Skeleton\",\"col\":2,\"row\":6},{\"action\":\"EndTurn\"}]\n",
    );
    let accepted_status = accepted
        .iter()
        .find(|line| line["type"] == "status")
        .unwrap();
    assert_eq!(accepted_status["results"][0]["ok"], true);
    assert!(accepted.iter().any(|line| {
        line["type"] == "events"
            && line["source"] == "llm"
            && line["events"]
                .as_array()
                .is_some_and(|events| events.iter().any(|event| event["kind"] == "recruit"))
    }));
}

#[test]
fn rust_action_shape_rejects_wrong_scalars_and_batch_count_overflow() {
    let lines = run_driver(
        &[
            "--scenario",
            "big_battle_6",
            "--faction0",
            "undead",
            "--faction1",
            "undead",
        ],
        "{\"action\":\"Move\",\"unit_id\":true,\"col\":1,\"row\":1}\n{\"action\":\"RecruitBatch\",\"def_id\":\"Skeleton\",\"count\":0}\n{\"action\":\"RecruitBatch\",\"def_id\":\"Skeleton\",\"count\":4294967296}\n{\"action\":\"Advance\",\"unit_id\":1,\"target_index\":1,\"def_id\":\"Skeleton\"}\n",
    );
    let statuses: Vec<&Value> = lines
        .iter()
        .filter(|line| line["type"] == "status")
        .collect();
    assert_eq!(statuses.len(), 4);
    assert!(statuses
        .iter()
        .all(|status| { status["ok"] == false && status["code"] == "parse" }));
}

#[test]
fn recruit_batch_reports_actual_partial_progress_and_rejects_unknown_type() {
    let partial = run_driver(
        &[
            "--scenario",
            "big_battle_6",
            "--faction0",
            "undead",
            "--faction1",
            "undead",
            "--gold",
            "15",
        ],
        "[{\"action\":\"RecruitBatch\",\"def_id\":\"Skeleton\",\"count\":2},{\"action\":\"EndTurn\"}]\n",
    );
    let partial_status = partial
        .iter()
        .find(|line| line["type"] == "status")
        .unwrap();
    assert_eq!(partial_status["results"][0]["ok"], true);
    assert_eq!(partial_status["results"][0]["requested"], 2);
    assert_eq!(partial_status["results"][0]["recruited"], 1);
    assert_eq!(partial_status["results"][0]["partial"], true);

    let unknown = run_driver(
        &[
            "--scenario",
            "big_battle_6",
            "--faction0",
            "undead",
            "--faction1",
            "undead",
        ],
        "[{\"action\":\"RecruitBatch\",\"def_id\":\"Orcish Grunt\",\"count\":1},{\"action\":\"EndTurn\"}]\n",
    );
    let unknown_status = unknown
        .iter()
        .find(|line| line["type"] == "status")
        .unwrap();
    assert_eq!(unknown_status["results"][0]["ok"], false);
    assert_eq!(unknown_status["results"][0]["code"], "NotInRecruitList");
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

fn tactical_surface_query(args: &[&str]) -> Value {
    let lines = run_driver(
        args,
        "{\"action\":\"Query\",\"what\":\"tactical_surface\"}\n",
    );
    lines
        .into_iter()
        .find(|line| line["what"] == "tactical_surface")
        .expect("tactical_surface response")
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
fn unit_type_profiles_preserve_signed_resistance_values() {
    let response = tactical_surface_query(&[
        "--scenario",
        "big_battle_6",
        "--faction0",
        "undead",
        "--faction1",
        "undead",
    ]);
    let profiles = response["body"]["unit_types"]
        .as_array()
        .expect("unit type profiles");
    let skeleton = profiles
        .iter()
        .find(|profile| profile["def_id"] == "Skeleton")
        .expect("Skeleton profile");

    assert_eq!(
        skeleton["resistance_semantics"],
        "signed_percent_damage_modifier"
    );
    assert_eq!(skeleton["resistances"]["blade"], -40);
    assert_eq!(skeleton["resistances"]["fire"], 20);
    assert_eq!(skeleton["abilities"], serde_json::json!(["submerge"]));
    assert_eq!(
        skeleton["advances_to"],
        serde_json::json!(["Revenant", "Deathblade"])
    );
}

#[test]
fn unit_type_profiles_preserve_attack_specials() {
    let response = tactical_surface_query(&[
        "--scenario",
        "big_battle_6",
        "--faction0",
        "undead",
        "--faction1",
        "undead",
    ]);
    let profiles = response["body"]["unit_types"]
        .as_array()
        .expect("unit type profiles");
    let corpse = profiles
        .iter()
        .find(|profile| profile["def_id"] == "Walking Corpse")
        .expect("Walking Corpse profile");

    assert_eq!(
        corpse["attacks"][0]["specials"],
        serde_json::json!(["plague"])
    );
}

#[test]
fn engage_reports_the_nested_engine_error_and_step_context() {
    let lines = run_driver(
        &[
            "--scenario", "big_battle_6", "--faction0", "undead", "--faction1", "undead",
            "--max-turns", "1", "--incremental-turns",
        ],
        r#"{"action":"Query","what":"validate_batch","state_revision":0,"orders":[{"action":"Engage","target_id":2,"steps":[{"attacker_id":1,"col":2,"row":7}]}]}
"#,
    );
    let status = lines
        .iter()
        .find(|line| line["type"] == "status")
        .expect("validation status");
    let result = &status["body"]["results"][0];
    assert_eq!(result["ok"], false);
    assert_eq!(result["code"], "NotAdjacent");
    assert_eq!(result["message"], "units are not in attack range");
    assert_eq!(result["step_index"], 0);
    assert_eq!(result["subaction"], "Attack");
    assert_eq!(result["attacker_id"], 1);
    assert_eq!(result["target_id"], 2);
    assert_eq!(result["nested"]["code"], "NotAdjacent");
    assert_eq!(status["body"]["valid"], false);

    let primitive = run_driver(
        &[
            "--scenario", "big_battle_6", "--faction0", "undead", "--faction1", "undead",
            "--max-turns", "1", "--incremental-turns",
        ],
        r#"{"action":"Query","what":"validate_batch","state_revision":0,"orders":[{"action":"Attack","attacker_id":1,"defender_id":2}]}
"#,
    );
    let primitive_status = primitive
        .iter()
        .find(|line| line["type"] == "status")
        .expect("primitive validation status");
    assert_eq!(primitive_status["body"]["results"][0]["code"], "NotAdjacent");

    let unreachable = run_driver(
        &[
            "--scenario", "big_battle_6", "--faction0", "undead", "--faction1", "undead",
            "--max-turns", "1", "--incremental-turns",
        ],
        r#"{"action":"Query","what":"validate_batch","state_revision":0,"orders":[{"action":"Engage","target_id":2,"steps":[{"attacker_id":1,"col":10,"row":7}]}]}
"#,
    );
    let unreachable_result = &unreachable
        .iter()
        .find(|line| line["type"] == "status")
        .expect("unreachable validation status")["body"]["results"][0];
    assert_eq!(unreachable_result["code"], "DestinationUnreachable");
    assert_eq!(unreachable_result["subaction"], "Move");
    assert_eq!(unreachable_result["step_index"], 0);
}

#[test]
fn stationary_engage_skips_steps_after_target_death_without_moving() {
    let fixture_root = concat!(env!("CARGO_MANIFEST_DIR"), "/tests/fixtures/s2_deterministic_duel");
    let lines = run_driver_with_env(
        &[
            "--scenario", "duel", "--faction0", "lethal", "--faction1", "fragile",
            "--max-turns", "1", "--incremental-turns",
        ],
        r#"[{"action":"Engage","target_id":2,"steps":[{"attacker_id":1,"col":0,"row":0},{"attacker_id":1,"col":0,"row":0}]}]
"#,
        &[("NORRUST_TEST_ROOT_DIR", fixture_root)],
    );
    let status = lines
        .iter()
        .find(|line| line["type"] == "status")
        .expect("engage status");
    assert_eq!(status["ok"], true);
    assert_eq!(status["results"].as_array().unwrap().len(), 1);
    let events = lines
        .iter()
        .find(|line| line["type"] == "events")
        .expect("engage events");
    let events = events["events"].as_array().unwrap();
    assert_eq!(events.iter().filter(|event| event["kind"] == "attack").count(), 1);
    assert_eq!(events.iter().filter(|event| event["kind"] == "move").count(), 0);
    assert_eq!(lines.last().unwrap()["type"], "game_end");
    assert_eq!(lines.last().unwrap()["reason"], "winner");
}

#[test]
fn promoted_friendly_type_enters_the_next_tactical_profile_set() {
    let fixture_root = concat!(env!("CARGO_MANIFEST_DIR"), "/tests/fixtures/s2_deterministic_duel");
    let lines = run_driver_with_env(
        &[
            "--scenario", "profile", "--faction0", "promoter", "--faction1", "lethal",
            "--max-turns", "1", "--incremental-turns",
        ],
        concat!(
            "[{\"action\":\"Attack\",\"attacker_id\":1,\"defender_id\":2},",
            "{\"action\":\"Advance\",\"unit_id\":1,\"def_id\":\"Promoted\"}]\n",
            "{\"action\":\"Query\",\"what\":\"tactical_surface\",\"state_revision\":2}\n",
        ),
        &[("NORRUST_TEST_ROOT_DIR", fixture_root)],
    );
    let query = lines
        .iter()
        .find(|line| line["type"] == "status" && line["what"] == "tactical_surface")
        .expect("post-advance tactical surface");
    let profiles = query["body"]["unit_types"].as_array().expect("profiles");
    let promoted = profiles
        .iter()
        .find(|profile| profile["def_id"] == "Promoted")
        .expect("promoted friendly definition");
    assert_eq!(promoted["level"], 2);
    assert!(lines.iter().any(|line| {
        line["type"] == "state"
            && line["turn_boundary"] == "partial"
            && line["units"]
                .as_array()
                .is_some_and(|units| units.iter().any(|unit| unit["def_id"] == "Promoted"))
    }));
}

#[test]
fn engage_preserves_missing_spent_and_later_step_errors_transactionally() {
    let missing = run_driver(
        &["--scenario", "big_battle_6", "--max-turns", "1", "--incremental-turns"],
        r#"[{"action":"Engage","target_id":999,"steps":[{"attacker_id":1,"col":2,"row":7}]}]
"#,
    );
    let missing_result = &missing
        .iter()
        .find(|line| line["type"] == "status")
        .expect("missing target status")["results"][0];
    assert_eq!(missing_result["code"], "UnitNotFound");
    assert!(missing_result["message"].as_str().unwrap().contains("999"));

    let spent = run_driver(
        &["--scenario", "big_battle_6", "--max-turns", "1", "--incremental-turns"],
        concat!(
            "[{\"action\":\"Move\",\"unit_id\":1,\"col\":3,\"row\":7}]\n",
            "[{\"action\":\"Engage\",\"target_id\":2,\"steps\":[{\"attacker_id\":1,\"col\":4,\"row\":7}]}]\n",
        ),
    );
    let spent_result = spent
        .iter()
        .filter(|line| line["type"] == "status")
        .last()
        .expect("spent status");
    assert_eq!(spent_result["ok"], true);
    assert_eq!(spent_result["results"][0]["code"], "UnitAlreadyMoved");
    assert_eq!(spent_result["results"][0]["subaction"], "Move");
    assert_eq!(spent_result["state_revision"], 1);
    assert_eq!(spent.iter().filter(|line| line["type"] == "state").count(), 2);

    let fixture_root = concat!(env!("CARGO_MANIFEST_DIR"), "/tests/fixtures/s2_deterministic_duel");
    let later = run_driver_with_env(
        &[
            "--scenario", "profile", "--faction0", "promoter", "--faction1", "lethal",
            "--max-turns", "1", "--incremental-turns",
        ],
        r#"[{"action":"Engage","target_id":2,"steps":[{"attacker_id":1,"col":0,"row":0},{"attacker_id":1,"col":0,"row":0}]}]
"#,
        &[("NORRUST_TEST_ROOT_DIR", fixture_root)],
    );
    let later_status = later
        .iter()
        .find(|line| line["type"] == "status")
        .expect("later-step status");
    let later_result = &later_status["results"][0];
    assert_eq!(later_result["code"], "UnitAlreadyAttacked");
    assert_eq!(later_result["step_index"], 1);
    assert_eq!(later_result["subaction"], "Attack");
    assert_eq!(later_result["attacker_id"], 1);
    assert!(later.iter().all(|line| line["type"] != "events"));
    assert_eq!(later_status["state_revision"], 0);
}

#[test]
fn tactical_surface_exposes_phase_modifiers_and_known_faction_pools() {
    let response = tactical_surface_query(&[
        "--scenario", "big_battle_6", "--faction0", "northerners", "--faction1", "loyalists",
    ]);
    let body = &response["body"];
    assert_eq!(body["time_of_day_modifiers"]["Dawn"]["chaotic"], 0);
    assert_eq!(body["time_of_day_modifiers"]["Dusk"]["lawful"], 0);
    assert_eq!(body["time_of_day_modifiers"]["Day"]["lawful"], 25);
    assert_eq!(body["time_of_day_modifiers"]["Day"]["chaotic"], -25);
    assert_eq!(body["time_of_day_modifiers"]["Night"]["lawful"], -25);
    assert_eq!(body["time_of_day_modifiers"]["Night"]["chaotic"], 25);
    let factions = body["factions"].as_array().expect("faction profiles");
    assert_eq!(factions[0]["name"], "Northerners");
    assert_eq!(factions[1]["name"], "Loyalists");
    assert!(factions[0]["recruit_ids"].as_array().unwrap().len() > 1);
    assert!(factions[1]["recruit_ids"].as_array().unwrap().len() > 1);
}

// `next_opponent_time_of_day` must reuse the same post-EndTurn projection as
// `threats.projected_time_of_day` / `exposure.projected_time_of_day`, and must
// diverge from the naive `next_time_of_day` (which always names the phase of
// the round after this one) whenever the query happens on the FIRST half of a
// round, since the opponent then acts before the round -- and its time of
// day -- advances.

#[test]
fn next_opponent_time_of_day_matches_current_phase_on_first_half_of_round() {
    // side 0 is active at game start: turn 1 (Dawn), no side has acted this
    // round yet. Ending side 0's turn only flips the active faction; the
    // round (and tod) does not advance until side 1 also ends its turn. So
    // the imminent opponent (side 1) shares the CURRENT phase, not the next
    // round's.
    let response = tactical_surface_query(&[
        "--scenario",
        "big_battle_6",
        "--faction0",
        "undead",
        "--faction1",
        "undead",
        "--llm-side",
        "0",
    ]);
    assert_eq!(response["body"]["time_of_day"], "Dawn");
    assert_eq!(response["body"]["next_round_time_of_day"], "Day");
    assert_eq!(response["body"]["next_opponent_time_of_day"], "Dawn");
    assert_ne!(
        response["body"]["next_opponent_time_of_day"],
        response["body"]["next_round_time_of_day"]
    );
    assert_eq!(
        response["body"]["next_opponent_time_of_day"],
        response["body"]["threats"]["projected_time_of_day"]
    );
    assert_eq!(
        response["body"]["next_opponent_time_of_day"],
        response["body"]["exposure"]["projected_time_of_day"]
    );
}

#[test]
fn next_opponent_time_of_day_matches_next_round_on_second_half_of_round() {
    // With the model on side 1, the driver auto-plays side 0's greedy turn
    // before handing control back, so the model's first query lands with
    // side 1 active, turn 1 (Dawn), one side already having acted this
    // round. Ending side 1's turn is the round's SECOND EndTurn, so it
    // advances both the round counter and the time of day: the imminent
    // opponent (side 0, next round) now agrees with the naive next-round
    // value.
    let response = tactical_surface_query(&[
        "--scenario",
        "big_battle_6",
        "--faction0",
        "undead",
        "--faction1",
        "undead",
        "--llm-side",
        "1",
    ]);
    assert_eq!(response["body"]["time_of_day"], "Dawn");
    assert_eq!(response["body"]["next_round_time_of_day"], "Day");
    assert_eq!(response["body"]["next_opponent_time_of_day"], "Day");
    assert_eq!(
        response["body"]["next_opponent_time_of_day"],
        response["body"]["next_round_time_of_day"]
    );
    assert_eq!(
        response["body"]["next_opponent_time_of_day"],
        response["body"]["threats"]["projected_time_of_day"]
    );
    assert_eq!(
        response["body"]["next_opponent_time_of_day"],
        response["body"]["exposure"]["projected_time_of_day"]
    );
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
    // The cap is hit right after the model's own EndTurn, before Greedy ever
    // gets a turn, so no further `type:"state"` boundary line is printed
    // (the live client would read one as "keep playing" and query the
    // exiting process). The terminal instead embeds the exact ending state
    // under `state`, matching this same terminal's own `state_revision`.
    assert!(!lines.iter().any(|line| line["type"] == "state"
        && line["state_revision"].as_u64() == terminal["state_revision"].as_u64()));
    assert_eq!(terminal["state"]["state_revision"], terminal["state_revision"]);
    assert_eq!(terminal["state"]["type"], "state");
    assert!(!lines.iter().any(|line| line["source"] == "greedy"));
}

/// Every early return in the interactive protocol -- winner, cap, timeout,
/// eof, and infrastructure failure -- must carry an explicit `state_revision`
/// so the importer can bind the terminal record to an exact snapshot instead
/// of guessing from ordinal position. This is a broad regression guard for
/// that contract rather than an exhaustive per-branch test.
#[test]
fn every_terminal_reason_carries_a_state_revision() {
    let lines = run_driver(
        &["--scenario", "big_battle_6", "--max-turns", "1"],
        "{\"action\":\"EndTurn\"}\n",
    );
    let terminal = lines.iter().find(|line| line["type"] == "game_end").unwrap();
    assert!(terminal.get("state_revision").is_some(), "{terminal:?}");
}

/// A terminal ending must never leak into the live wire protocol as an extra
/// `type:"state"` boundary line -- the interactive client treats any bare one
/// as "it is your turn," and would query (and write to) an already-exiting
/// driver process. The proven ending snapshot travels embedded inside
/// `game_end` itself instead.
#[test]
fn a_terminal_ending_never_prints_a_trailing_state_boundary_line() {
    let lines = run_driver(
        &["--scenario", "big_battle_6", "--max-turns", "1"],
        "{\"action\":\"EndTurn\"}\n",
    );
    let terminal_index = lines.iter().position(|line| line["type"] == "game_end").unwrap();
    assert!(!lines[terminal_index + 1..].iter().any(|line| line["type"] == "state"));
}

#[test]
fn resume_from_a_postbatch_checkpoint_runs_the_pending_opponent_turn_exactly_once() {
    let checkpoint_dir = env::temp_dir().join(format!(
        "norrust-driver-protocol-resume-test-{}",
        std::process::id()
    ));
    let _ = fs::remove_dir_all(&checkpoint_dir);
    let base_args = [
        "--scenario",
        "big_battle_6",
        "--faction0",
        "undead",
        "--faction1",
        "undead",
        "--max-turns",
        "50",
    ];
    let checkpoint_dir_str = checkpoint_dir.to_string_lossy().into_owned();
    let mut first_args: Vec<&str> = base_args.to_vec();
    first_args.push("--checkpoint-dir");
    first_args.push(&checkpoint_dir_str);
    let first_lines = run_driver(&first_args, "{\"action\":\"EndTurn\"}\n");

    // The "postbatch" checkpoint is written right after the model's own
    // EndTurn commits and before Greedy's response runs -- resuming from it
    // must replay exactly that one pending opponent turn, never zero and
    // never two.
    let postbatch = first_lines
        .iter()
        .find(|line| line["type"] == "checkpoint" && line["boundary"] == "postbatch")
        .expect("driver must publish a postbatch checkpoint before running greedy");
    assert_eq!(postbatch["pending_opponent_turn"], true);
    let checkpoint_path = checkpoint_dir.join(postbatch["path"].as_str().unwrap());
    assert!(checkpoint_path.is_file(), "checkpoint file must exist on disk");

    let mut resume_args: Vec<&str> = base_args.to_vec();
    resume_args.push("--resume-checkpoint");
    let checkpoint_path_str = checkpoint_path.to_string_lossy().into_owned();
    resume_args.push(&checkpoint_path_str);
    let resumed_lines = run_driver(&resume_args, "");

    let greedy_event_blocks = resumed_lines
        .iter()
        .filter(|line| line["type"] == "events" && line["source"] == "greedy")
        .count();
    assert_eq!(
        greedy_event_blocks, 1,
        "resume must run the one pending opponent turn, not zero or two: {resumed_lines:?}"
    );
    let opening = resumed_lines
        .iter()
        .find(|line| line["type"] == "state")
        .expect("resume must print a boundary once the pending turn resolves");
    // side_turns for a resumed "postbatch" checkpoint is the model's own just
    // completed turn (1); the pending greedy turn resuming here adds exactly
    // one more, never a second re-application of the model's own turn.
    assert_eq!(postbatch["side_turns"], 1);
    assert!(
        opening.get("state_revision").is_some(),
        "the post-resume boundary must carry an exact revision"
    );

    let _ = fs::remove_dir_all(&checkpoint_dir);
}

// ── MoveGroupToward (stack 5: delegate movement without ending the turn) ──

const MOVE_GROUP_ARGS: [&str; 11] = [
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
    "--incremental-turns",
];

#[test]
fn move_group_toward_moves_named_units_and_stays_within_one_side_turn() {
    // Recruit two units, deploy them as a group toward a rally hex, then
    // finish -- all as separate incremental batches inside one side turn.
    // This is the plan's "recruit, deploy, recruit again" shape distilled to
    // its minimal proof: the group step must not itself end the turn.
    let lines = run_driver(
        &["--scenario", "big_battle_6", "--faction0", "undead", "--faction1", "undead",
          "--gold", "100", "--max-turns", "4", "--incremental-turns"],
        concat!(
            "[{\"action\":\"Recruit\",\"def_id\":\"Skeleton\",\"col\":3,\"row\":7},",
            "{\"action\":\"Recruit\",\"def_id\":\"Skeleton\",\"col\":3,\"row\":6}]\n",
            "[{\"action\":\"MoveGroupToward\",\"unit_ids\":[3,4],\"col\":10,\"row\":7}]\n",
            "[{\"action\":\"FinishWithGreedy\",\"groups\":[],\"holds\":[]}]\n",
        ),
    );
    let statuses: Vec<&Value> = lines.iter().filter(|line| line["type"] == "status").collect();
    assert_eq!(statuses.len(), 3);
    assert!(statuses.iter().all(|status| status["ok"] == true));

    // The recruit batch and the move batch are both partial: only the final
    // FinishWithGreedy line ends the side turn. `boundaries[0]` is the
    // opening pre-input snapshot; `[1]` and `[2]` follow the two partial
    // batches.
    let boundaries: Vec<&Value> = lines.iter().filter(|line| line["type"] == "state").collect();
    assert!(boundaries[1]["turn_boundary"] == "partial");
    assert!(boundaries[2]["turn_boundary"] == "partial");

    let move_result = &statuses[1]["results"][0];
    assert_eq!(move_result["ok"], true);
    let moved = move_result["moved"].as_array().expect("moved list");
    assert_eq!(moved.len(), 2);
    let moved_ids: Vec<u64> = moved.iter().map(|entry| entry["unit_id"].as_u64().unwrap()).collect();
    assert_eq!(moved_ids, vec![3, 4]);
    assert_eq!(move_result["skipped"].as_array().unwrap().len(), 0);
    for entry in moved {
        assert_ne!(entry["from"], entry["to"], "a reported move must be an actual displacement");
    }

    // The generated moves are macro output, not individually authored --
    // they must appear in a delegated_greedy envelope, distinct from the
    // llm envelope carrying the two authored Recruit orders.
    let recruit_events = lines
        .iter()
        .find(|line| line["type"] == "events" && line["source"] == "llm")
        .expect("authored recruit events");
    assert!(recruit_events["events"]
        .as_array()
        .unwrap()
        .iter()
        .all(|event| event["kind"] == "recruit" && event["source"] == "llm"));
    let move_events = lines
        .iter()
        .find(|line| {
            line["type"] == "events"
                && line["source"] == "delegated_greedy"
                && line["events"].as_array().is_some_and(|events| {
                    events.iter().any(|event| event["kind"] == "move")
                })
        })
        .expect("delegated move events");
    assert!(move_events["events"]
        .as_array()
        .unwrap()
        .iter()
        .all(|event| event["kind"] == "move" && event["source"] == "delegated_greedy"));
    assert!(move_events["events"]
        .as_array()
        .unwrap()
        .iter()
        .all(|event| event["delegated_order_index"] == 0));
    // Movement-only: no attack, recruit, advance, or end_turn event may share
    // this delegated envelope with the generated moves.
    assert!(!move_events["events"]
        .as_array()
        .unwrap()
        .iter()
        .any(|event| !matches!(event["kind"].as_str(), Some("move"))));
}

// Order-dependent recomputation against a genuinely contested hex is proven
// precisely, with an engineered board, in
// `ai::tests::toward_hex_recomputes_after_earlier_units_move_in_submission_order`,
// which exercises the exact function this action calls per unit. This test
// instead covers the driver-level claim that is specific to this action: the
// rally hex may be occupied at all, by an enemy, without rejecting the batch
// or forcing a collision between the group's own units.
#[test]
fn move_group_toward_accepts_an_occupied_rally_hex_as_a_direction() {
    let lines = run_driver(
        &["--scenario", "big_battle_6", "--faction0", "undead", "--faction1", "undead",
          "--gold", "100", "--max-turns", "4", "--incremental-turns"],
        concat!(
            "[{\"action\":\"Recruit\",\"def_id\":\"Skeleton\",\"col\":3,\"row\":7},",
            "{\"action\":\"Recruit\",\"def_id\":\"Skeleton\",\"col\":3,\"row\":6}]\n",
            // The enemy leader's own keep hex: certainly occupied.
            "[{\"action\":\"MoveGroupToward\",\"unit_ids\":[3,4],\"col\":21,\"row\":6}]\n",
            "[{\"action\":\"FinishWithGreedy\",\"groups\":[],\"holds\":[]}]\n",
        ),
    );
    let statuses: Vec<&Value> = lines.iter().filter(|line| line["type"] == "status").collect();
    assert!(statuses.iter().all(|status| status["ok"] == true), "{statuses:?}");
    let moved = statuses[1]["results"][0]["moved"].as_array().unwrap();
    assert_eq!(moved.len(), 2, "an occupied rally hex must not block a legal group move");
    assert_ne!(moved[0]["to"], moved[1]["to"], "the two units cannot land on the same hex");
    for entry in moved {
        let to = &entry["to"];
        assert!(
            !(to["col"] == 21 && to["row"] == 6),
            "the occupied target itself is never a legal destination"
        );
    }
}

#[test]
fn move_group_toward_gives_spent_and_no_progress_units_an_explicit_skip() {
    let lines = run_driver(
        &["--scenario", "big_battle_6", "--faction0", "undead", "--faction1", "undead",
          "--gold", "100", "--max-turns", "4", "--incremental-turns"],
        concat!(
            "[{\"action\":\"Recruit\",\"def_id\":\"Skeleton\",\"col\":3,\"row\":7}]\n",
            // Already at the rally hex: no reachable destination is
            // strictly closer than the unit's own position.
            "[{\"action\":\"MoveGroupToward\",\"unit_ids\":[3],\"col\":3,\"row\":7}]\n",
            // Moves the unit for real, then targets it again in the same
            // batch: the second attempt must see it as spent.
            "[{\"action\":\"MoveGroupToward\",\"unit_ids\":[3],\"col\":10,\"row\":7},",
            "{\"action\":\"MoveGroupToward\",\"unit_ids\":[3],\"col\":10,\"row\":7}]\n",
            "[{\"action\":\"FinishWithGreedy\",\"groups\":[],\"holds\":[]}]\n",
        ),
    );
    let statuses: Vec<&Value> = lines.iter().filter(|line| line["type"] == "status").collect();
    assert!(statuses.iter().all(|status| status["ok"] == true), "{statuses:?}");

    let no_progress = &statuses[1]["results"][0];
    assert_eq!(no_progress["moved"].as_array().unwrap().len(), 0);
    assert_eq!(no_progress["skipped"][0]["unit_id"], 3);
    assert_eq!(no_progress["skipped"][0]["reason"], "no_improving_destination");

    let real_move = &statuses[2]["results"][0];
    assert_eq!(real_move["moved"].as_array().unwrap().len(), 1);
    let repeat_attempt = &statuses[2]["results"][1];
    assert_eq!(repeat_attempt["moved"].as_array().unwrap().len(), 0);
    assert_eq!(repeat_attempt["skipped"][0]["unit_id"], 3);
    assert_eq!(repeat_attempt["skipped"][0]["reason"], "spent");
}

#[test]
fn move_group_toward_permits_an_explicit_recruiter_with_manual_loss_of_keep() {
    // The model's own leader (id 1) can be named explicitly. Moving it off
    // the keep has the same recruiting consequence a manual Move would have.
    let lines = run_driver(
        &["--scenario", "big_battle_6", "--faction0", "undead", "--faction1", "undead",
          "--gold", "100", "--max-turns", "4", "--incremental-turns"],
        concat!(
            "[{\"action\":\"MoveGroupToward\",\"unit_ids\":[1],\"col\":10,\"row\":7}]\n",
            "[{\"action\":\"FinishWithGreedy\",\"groups\":[],\"holds\":[]}]\n",
            "[{\"action\":\"Recruit\",\"def_id\":\"Skeleton\",\"col\":3,\"row\":7}]\n",
        ),
    );
    let statuses: Vec<&Value> = lines.iter().filter(|line| line["type"] == "status").collect();
    let move_result = &statuses[0]["results"][0];
    assert_eq!(move_result["moved"][0]["unit_id"], 1);
    // Once the model's next turn comes back around, the leader is still off
    // the keep it left under its own power, so recruiting fails exactly as
    // it would after any other manual departure.
    assert_eq!(statuses[2]["results"][0]["code"], "LeaderNotOnKeep");
}

#[test]
fn move_group_toward_never_attacks_recruits_or_ends_the_turn() {
    let lines = run_driver(
        &MOVE_GROUP_ARGS,
        "[{\"action\":\"MoveGroupToward\",\"unit_ids\":[1],\"col\":10,\"row\":7}]\n",
    );
    let status = lines.iter().find(|line| line["type"] == "status").expect("move status");
    assert_eq!(status["ok"], true);
    assert!(status.get("finish_kind").is_none(), "a nonfinal move must not report a finish kind");
    // The first "state" line is the opening pre-input snapshot; the second
    // is the boundary printed after this move batch.
    let boundary = lines
        .iter()
        .filter(|line| line["type"] == "state")
        .nth(1)
        .expect("partial boundary");
    assert_eq!(boundary["turn_boundary"], "partial");
    assert_eq!(boundary["active_faction"], 0, "the opponent must not be activated");
    let events = lines.iter().find(|line| line["type"] == "events").expect("move events");
    assert!(events["events"].as_array().unwrap().iter().all(|event| {
        matches!(event["kind"].as_str(), Some("move"))
    }));
    // Stdin closes right after this one partial batch, so the driver's own
    // end-of-input shutdown is expected -- the claim under test is that
    // MoveGroupToward itself never ends the turn or activates the opponent,
    // not that the process runs forever.
    let terminal = lines.iter().find(|line| line["type"] == "game_end");
    if let Some(terminal) = terminal {
        assert_eq!(terminal["reason"], "eof");
        assert_eq!(terminal["side_turns"], 0, "the side turn never closed");
    }
}

#[test]
fn move_group_toward_rejects_duplicate_foreign_and_enemy_ids_before_mutation() {
    let lines = run_driver(
        &MOVE_GROUP_ARGS,
        concat!(
            "[{\"action\":\"MoveGroupToward\",\"unit_ids\":[1,1],\"col\":10,\"row\":7}]\n",
            "[{\"action\":\"MoveGroupToward\",\"unit_ids\":[999],\"col\":10,\"row\":7}]\n",
            "[{\"action\":\"MoveGroupToward\",\"unit_ids\":[2],\"col\":10,\"row\":7}]\n",
        ),
    );
    let statuses: Vec<&Value> = lines.iter().filter(|line| line["type"] == "status").collect();
    assert_eq!(statuses[0]["code"], "parse", "duplicate ids in one order are malformed shape");
    assert_eq!(statuses[1]["code"], "unauthorized_unit", "a nonexistent id is never guessed at");
    assert_eq!(statuses[2]["code"], "unauthorized_unit", "the enemy leader is not a model-side unit");
    // Only the opening pre-input snapshot may appear -- every rejected batch
    // above is caught before any mutation, so none of them commits a state
    // boundary or an events line of its own.
    assert_eq!(lines.iter().filter(|line| line["type"] == "state").count(), 1);
    assert!(!lines.iter().any(|line| line["type"] == "events"));
}

#[test]
fn move_group_toward_rejects_an_out_of_bounds_target_and_rolls_back_only_that_batch() {
    let lines = run_driver(
        &["--scenario", "big_battle_6", "--faction0", "undead", "--faction1", "undead",
          "--gold", "100", "--max-turns", "4", "--incremental-turns"],
        concat!(
            "[{\"action\":\"Recruit\",\"def_id\":\"Skeleton\",\"col\":3,\"row\":7}]\n",
            "[{\"action\":\"MoveGroupToward\",\"unit_ids\":[3],\"col\":10,\"row\":7}]\n",
            "[{\"action\":\"MoveGroupToward\",\"unit_ids\":[3],\"col\":999999,\"row\":7}]\n",
            "[{\"action\":\"FinishWithGreedy\",\"groups\":[],\"holds\":[]}]\n",
        ),
    );
    let statuses: Vec<&Value> = lines.iter().filter(|line| line["type"] == "status").collect();
    assert_eq!(statuses.len(), 4);
    assert_eq!(statuses[0]["ok"], true);
    assert_eq!(statuses[1]["ok"], true);
    assert_eq!(statuses[2]["results"][0]["code"], "DestinationOutOfBounds");
    // The rejected batch's revision must equal the last accepted one -- the
    // earlier recruit and successful move stay committed, and only the
    // failed batch itself is rolled back.
    assert_eq!(statuses[2]["state_revision"], statuses[1]["state_revision"]);
    assert_eq!(statuses[3]["ok"], true);
    assert!(statuses[3]["state_revision"].as_u64() > statuses[1]["state_revision"].as_u64());
}

// The pre-stack-5 finishing macros keep exactly their existing shape: a
// FinishWithGreedy-only batch still produces a single delegated_greedy
// envelope, unaffected by MoveGroupToward's ability to split that envelope
// when it runs first in the same batch.
#[test]
fn move_group_toward_and_finish_with_greedy_share_one_delegated_envelope_when_adjacent() {
    let lines = run_driver(
        &MOVE_GROUP_ARGS,
        "[{\"action\":\"MoveGroupToward\",\"unit_ids\":[1],\"col\":10,\"row\":7},{\"action\":\"FinishWithGreedy\",\"groups\":[],\"holds\":[]}]\n",
    );
    let delegated: Vec<&Value> = lines
        .iter()
        .filter(|line| line["type"] == "events" && line["source"] == "delegated_greedy")
        .collect();
    assert_eq!(
        delegated.len(),
        1,
        "adjacent delegating orders with no authored event between them must not fragment"
    );
    let kinds: Vec<&str> = delegated[0]["events"]
        .as_array()
        .unwrap()
        .iter()
        .map(|event| event["kind"].as_str().unwrap())
        .collect();
    assert!(kinds.contains(&"move"));
    assert!(kinds.contains(&"end_turn"));
    assert_eq!(delegated[0]["finish_kind"], "selective");
}

#[test]
fn move_group_toward_preserves_macro_indices_across_authored_interleaving() {
    // The two movement macros are separated by an ordinary authored Move. The
    // wire envelopes may split around that event, but each generated event
    // must retain the zero-based authored action index that produced it.
    let lines = run_driver(
        &["--scenario", "big_battle_6", "--faction0", "undead", "--faction1", "undead",
          "--gold", "100", "--max-turns", "1", "--incremental-turns"],
        concat!(
            "[{\"action\":\"RecruitBatch\",\"def_id\":\"Skeleton\",\"count\":3}]\n",
            "[{\"action\":\"MoveGroupToward\",\"unit_ids\":[3],\"col\":10,\"row\":7},",
            "{\"action\":\"Move\",\"unit_id\":1,\"col\":1,\"row\":7},",
            "{\"action\":\"MoveGroupToward\",\"unit_ids\":[4],\"col\":10,\"row\":7},",
            "{\"action\":\"FinishWithGreedy\",\"groups\":[],\"holds\":[]}]\n",
        ),
    );
    let statuses: Vec<&Value> = lines.iter().filter(|line| line["type"] == "status").collect();
    assert!(statuses.iter().all(|status| status["ok"] == true), "{statuses:?}");
    assert_eq!(statuses[1]["results"].as_array().unwrap().len(), 4);

    let event_lines: Vec<&Value> = lines.iter().filter(|line| line["type"] == "events").collect();
    assert_eq!(event_lines.len(), 4, "recruit plus delegated/authored/delegated segments should remain observable");
    assert_eq!(event_lines[0]["source"], "llm");
    assert_eq!(event_lines[1]["source"], "delegated_greedy");
    assert_eq!(event_lines[2]["source"], "llm");
    assert_eq!(event_lines[3]["source"], "delegated_greedy");
    assert!(event_lines[1]["events"].as_array().unwrap().iter().all(|event| {
        event["kind"] == "move" && event["delegated_order_index"] == 0
    }));
    assert!(event_lines[2]["events"].as_array().unwrap().iter().all(|event| {
        event["kind"] == "move" && event.get("delegated_order_index").is_none()
    }));
    assert!(event_lines[3]["events"].as_array().unwrap().iter().all(|event| {
        event["delegated_order_index"] == 2 || event["delegated_order_index"] == 3
    }));
    assert!(event_lines[3]["events"].as_array().unwrap().iter().any(|event| {
        event["kind"] == "move" && event["delegated_order_index"] == 2
    }));
    assert!(event_lines[3]["events"].as_array().unwrap().iter().any(|event| {
        event["kind"] == "end_turn" && event["delegated_order_index"] == 3
    }));
}
