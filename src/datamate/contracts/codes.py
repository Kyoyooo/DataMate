"""Reason codes (SPEC §10.2, P1 subset). Owner: Lead.

A code is never reused with a different meaning. The comment names the
component that raises it so error analysis can route failures to an owner.
"""

# Decisions (decision/)
D_ANSWER = "D_ANSWER"
D_UNANSWERABLE_CONFIRMED = "D_UNANSWERABLE_CONFIRMED"  # parser said missing field; catalog agrees
D_UNANSWERABLE_OUT_OF_RANGE = "D_UNANSWERABLE_OUT_OF_RANGE"  # a window has zero data coverage
D_IMPLAUSIBLE = "D_IMPLAUSIBLE"  # NaN / Infinity / absurd percent

# Inputs (runtime/)
E_INPUT_BUSINESS_MISSING = "E_INPUT_BUSINESS_MISSING"
E_BUSINESS_SETUP = "E_BUSINESS_SETUP"  # catalog/

# Parse and time (parse/, temporal/)
E_PARSE_INVALID = "E_PARSE_INVALID"
E_TIME_UNSUPPORTED = "E_TIME_UNSUPPORTED"

# Model calls (llm/)
E_MODEL_ERROR = "E_MODEL_ERROR"
E_SCRIPT_MISS = "E_SCRIPT_MISS"  # ScriptedModelClient has no response (dev/tests only)

# Solver and execution (solver/, sandbox/)
E_SOLVER_OUTPUT_INVALID = "E_SOLVER_OUTPUT_INVALID"
E_SQL_NOT_SELECT = "E_SQL_NOT_SELECT"
E_SQL_NONDETERMINISTIC = "E_SQL_NONDETERMINISTIC"
E_SQL_EXEC = "E_SQL_EXEC"
E_SQL_TIMEOUT = "E_SQL_TIMEOUT"
E_EMPTY_RESULT = "E_EMPTY_RESULT"  # no rows, or NULL: missing information, never zero
E_TYPE_CONTRACT = "E_TYPE_CONTRACT"
E_NO_SUCCESS = "E_NO_SUCCESS"

# Runtime (runtime/)
E_INTERNAL = "E_INTERNAL"
E_DUPLICATE_WRITE = "E_DUPLICATE_WRITE"
