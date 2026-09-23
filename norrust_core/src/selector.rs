//! Versioned, provider-independent contract for choosing among complete
//! Coordinated Planner candidates. The contract contains summaries only; the
//! executable plans stay inside the engine.

use serde::{Deserialize, Serialize};

pub const SELECTOR_SCHEMA_VERSION: u16 = 1;

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SelectorRequest {
    pub schema_version: u16,
    pub turn: u32,
    pub side: u8,
    pub state_revision: u64,
    pub evaluation_seed: u64,
    pub objective: String,
    pub candidates: Vec<CandidateSummary>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct CandidateSummary {
    pub candidate_id: String,
    pub plan_kind: String,
    pub label: String,
    pub score: f32,
    pub material_delta: f32,
    pub gold_delta: i64,
    pub village_delta: i32,
    pub recruiter_alive: bool,
    pub objective_progress: f32,
    /// Utility change caused by the modeled opponent response, measured from
    /// the state immediately after our plan to the state after its response.
    pub opponent_response_delta: f32,
    pub legal: bool,
    pub state_revision: u64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SelectorResponse {
    pub schema_version: u16,
    pub candidate_id: String,
    #[serde(default)]
    pub reason_code: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct CandidateTelemetry {
    pub candidate_id: String,
    pub score: f32,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct DecisionTelemetry {
    pub schema_version: u16,
    pub state_revision: u64,
    pub candidates: Vec<CandidateTelemetry>,
    pub baseline_candidate_id: String,
    pub selected_candidate_id: String,
    pub score_margin: f32,
    pub selector_invoked: bool,
    pub response_status: String,
    pub fallback_reason: Option<String>,
    pub latency_ms: Option<u64>,
    pub input_tokens: Option<u32>,
    pub output_tokens: Option<u32>,
    pub cost_microusd: Option<u64>,
}

impl SelectorRequest {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.schema_version != SELECTOR_SCHEMA_VERSION {
            return Err("unsupported selector request schema version");
        }
        if self.candidates.is_empty() {
            return Err("selector request must contain candidates");
        }
        if self.candidates.iter().any(|candidate| {
            !candidate.legal || candidate.state_revision != self.state_revision
        }) {
            return Err("candidate is illegal or belongs to a different state revision");
        }
        for (index, candidate) in self.candidates.iter().enumerate() {
            if self.candidates[..index]
                .iter()
                .any(|prior| prior.candidate_id == candidate.candidate_id)
            {
                return Err("candidate IDs must be unique");
            }
        }
        Ok(())
    }
}

impl SelectorResponse {
    pub fn validate_for(&self, request: &SelectorRequest) -> Result<(), &'static str> {
        if self.schema_version != SELECTOR_SCHEMA_VERSION {
            return Err("unsupported selector response schema version");
        }
        request.validate()?;
        if !request
            .candidates
            .iter()
            .any(|candidate| candidate.candidate_id == self.candidate_id)
        {
            return Err("selected candidate ID is not in the current request");
        }
        if self.reason_code.as_ref().is_some_and(|reason| reason.len() > 32) {
            return Err("reason code exceeds 32 bytes");
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn request() -> SelectorRequest {
        SelectorRequest {
            schema_version: SELECTOR_SCHEMA_VERSION,
            turn: 4,
            side: 0,
            state_revision: 19,
            evaluation_seed: 77,
            objective: "Protect".into(),
            candidates: vec![CandidateSummary {
                candidate_id: "greedy".into(),
                plan_kind: "greedy".into(),
                label: "Greedy baseline".into(),
                score: 12.5,
                material_delta: 1.0,
                gold_delta: -4,
                village_delta: 0,
                recruiter_alive: true,
                objective_progress: 2.0,
                opponent_response_delta: -1.25,
                legal: true,
                state_revision: 19,
            }],
        }
    }

    #[test]
    fn request_round_trips_and_rejects_unknown_version() {
        let value = request();
        let json = serde_json::to_string(&value).unwrap();
        let decoded: SelectorRequest = serde_json::from_str(&json).unwrap();
        assert_eq!(decoded, value);
        let mut unsupported = decoded;
        unsupported.schema_version += 1;
        assert_eq!(unsupported.validate(), Err("unsupported selector request schema version"));
    }

    #[test]
    fn request_rejects_duplicate_or_stale_candidates() {
        let mut value = request();
        value.candidates.push(value.candidates[0].clone());
        assert_eq!(value.validate(), Err("candidate IDs must be unique"));
        value.candidates.pop();
        value.candidates[0].state_revision += 1;
        assert!(value.validate().is_err());
    }

    #[test]
    fn response_accepts_only_a_current_candidate_id() {
        let value = request();
        let valid = SelectorResponse {
            schema_version: SELECTOR_SCHEMA_VERSION,
            candidate_id: "greedy".into(),
            reason_code: Some("protect_recruiter".into()),
        };
        assert!(valid.validate_for(&value).is_ok());
        let unknown = SelectorResponse { candidate_id: "invented".into(), ..valid };
        assert!(unknown.validate_for(&value).is_err());
    }
}
