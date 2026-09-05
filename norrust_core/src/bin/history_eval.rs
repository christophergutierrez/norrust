use rusqlite::{params, Connection};
use std::env;
use std::process;
use std::time::{SystemTime, UNIX_EPOCH};

fn now() -> String {
    SystemTime::now().duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs().to_string()).unwrap_or_else(|_| "0".into())
}

fn mechanical(db: &str, cohort: Option<&str>) -> rusqlite::Result<String> {
    let conn = Connection::open(db)?;
    conn.execute_batch("PRAGMA foreign_keys=ON; BEGIN IMMEDIATE;")?;
    let run_id = format!("mechanical_v1:{}", now());
    conn.execute(
        "INSERT INTO evaluation_runs
         (evaluation_run_id,evaluator_name,evaluator_version,config_json,started_at,status)
         VALUES(?1,'mechanical','1','{}',?2,'running')",
        params![run_id, now()],
    )?;
    let query = if cohort.is_some() {
        "SELECT r.request_id,r.response_blob,r.prompt_blob FROM model_requests r
         JOIN games g ON g.game_id=r.game_id WHERE g.cohort_id=?1"
    } else {
        "SELECT request_id,response_blob,prompt_blob FROM model_requests"
    };
    let mut stmt = conn.prepare(query)?;
    let rows: Vec<(String, Option<Vec<u8>>, Option<Vec<u8>>)> = if let Some(value) = cohort {
        stmt.query_map(params![value], |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, Option<Vec<u8>>>(1)?,
                row.get::<_, Option<Vec<u8>>>(2)?))
        })?.collect::<rusqlite::Result<_>>()?
    } else {
        stmt.query_map([], |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, Option<Vec<u8>>>(1)?,
                row.get::<_, Option<Vec<u8>>>(2)?))
        })?.collect::<rusqlite::Result<_>>()?
    };
    drop(stmt);
    for (request_id, response, prompt) in rows {
        let (verdict, reason) = if prompt.is_some() && response.is_some() {
            ("pass", "payloads_present")
        } else {
            ("unknown", "missing_payload")
        };
        conn.execute(
            "INSERT INTO decision_evaluations
             (evaluation_run_id,request_id,verdict,reason_codes_json,metrics_json,evidence_json)
             VALUES(?1,?2,?3,?4,'{}',?5)",
            params![run_id, request_id, verdict, format!("[\"{}\"]", reason),
                    "{\"evaluator\":\"mechanical_v1\"}"],
        )?;
    }
    conn.execute("UPDATE evaluation_runs SET completed_at=?1,status='complete' WHERE evaluation_run_id=?2",
                 params![now(), run_id])?;
    conn.execute_batch("COMMIT;")?;
    Ok(run_id)
}

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() < 4 || args[1] != "mechanical" {
        eprintln!("usage: history_eval mechanical --db DB [--cohort COHORT]");
        process::exit(2);
    }
    let mut db = None;
    let mut cohort = None;
    let mut i = 2;
    while i < args.len() {
        match args[i].as_str() {
            "--db" if i + 1 < args.len() => { db = Some(args[i + 1].as_str()); i += 2; }
            "--cohort" if i + 1 < args.len() => { cohort = Some(args[i + 1].as_str()); i += 2; }
            _ => { eprintln!("unknown argument: {}", args[i]); process::exit(2); }
        }
    }
    match mechanical(db.expect("--db is required"), cohort) {
        Ok(run_id) => println!("{}", run_id),
        Err(error) => { eprintln!("history evaluation failed: {error}"); process::exit(1); }
    }
}
