# UI and catalog requirements

> Navigation: [requirements index](README.md)

Read with `design.md` when changing catalog navigation or ordinary operator controls.

| ID | Requirement | Rationale / verification intent |
|---|---|---|
| `REQ-UI-001` | Case-bound submission or execution-profile selection must appear as a subordinate layer directly beneath the selected mission case in the catalog's left navigation hierarchy. The selected submission's rationale, owner, feasibility, evidence gate, and learning value remain in the right detail pane with the mission-case information. | Separates navigation from explanation, makes the case-to-submission relationship visible, and avoids embedding a selector inside its own evidence card. |
| `REQ-UI-002` | Ordinary mission preparation uses concise one-word operator labels for its directly adjustable controls and omits implementation labels and routine `Eligible` badges. Every discovered simulation mission remains enabled regardless of implementation or qualification metadata; planner, backend, and hard safety checks run after selection and preserve their exact failure reason. Unavailable optional technical submissions remain visibly disabled, while hashes, internal planner/profile names, eligibility mechanics, and full evidence status stay in the closed technical disclosure. | Keeps the complete simulation catalog directly playable without weakening execution-time safety or hiding technical traceability. |
