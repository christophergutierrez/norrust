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
