// GENERATED from docs/contracts/fixtures/plugin_grant_v2/*.json by
// tools/sync_fixtures.py. Do not edit by hand.
export const GRANT_GOLDEN: Record<string, any> = {
  "decision": {
    "activity_ids": [
      "activity_000000000000000000000000000f4246"
    ],
    "contracts": [
      {
        "contract_id": "api.gamma",
        "version": 1
      }
    ],
    "modules": [
      "gamma"
    ],
    "split_id": "split_000000000000000000000000000f4243",
    "status": "approved"
  },
  "exchange": {
    "grant": {
      "activated_at": "2026-10-05T12:00:00.000000Z",
      "conversation_ids": [
        "conv_00000000000000000000000000000001"
      ],
      "created_at": "2026-10-05T12:00:00.000000Z",
      "expires_at": "2026-10-05T13:00:00.000000Z",
      "grant_id": "grant_fixture00000000000000000000000001",
      "host": "claude-code",
      "last_used_at": null,
      "revoked_at": null,
      "scopes": [
        "board.split.decide"
      ],
      "status": "active",
      "use_count": 0
    },
    "schema_version": "plugin_grant_exchange/v2",
    "secret": "xpg_grant_fixture00000000000000000000000001_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
  },
  "issue": {
    "grant": {
      "activated_at": null,
      "conversation_ids": [
        "conv_00000000000000000000000000000001"
      ],
      "created_at": "2026-10-05T12:00:00.000000Z",
      "expires_at": "2026-10-05T12:02:00.000000Z",
      "grant_id": "grant_fixture00000000000000000000000001",
      "host": "claude-code",
      "last_used_at": null,
      "revoked_at": null,
      "scopes": [
        "board.split.decide"
      ],
      "status": "pending",
      "use_count": 0
    },
    "pairing_code": "AAAA-AAAA",
    "pairing_expires_at": "2026-10-05T12:02:00.000000Z",
    "schema_version": "plugin_grant_issue/v2"
  },
  "list": {
    "conversation_id": "conv_00000000000000000000000000000001",
    "grants": [
      {
        "activated_at": null,
        "conversation_ids": [
          "conv_00000000000000000000000000000001"
        ],
        "created_at": "2026-10-05T12:00:00.000000Z",
        "expires_at": "2026-10-05T12:02:00.000000Z",
        "grant_id": "grant_fixture00000000000000000000000005",
        "host": "host-revoked",
        "last_used_at": null,
        "revoked_at": "2026-10-05T12:00:00.000000Z",
        "scopes": [
          "board.split.decide"
        ],
        "status": "revoked",
        "use_count": 0
      },
      {
        "activated_at": null,
        "conversation_ids": [
          "conv_00000000000000000000000000000001"
        ],
        "created_at": "2026-10-05T12:00:00.000000Z",
        "expires_at": "2026-01-01T00:00:00.000000Z",
        "grant_id": "grant_fixture00000000000000000000000004",
        "host": "host-expired",
        "last_used_at": null,
        "revoked_at": null,
        "scopes": [
          "board.split.decide"
        ],
        "status": "expired",
        "use_count": 0
      },
      {
        "activated_at": "2026-10-05T12:00:00.000000Z",
        "conversation_ids": [
          "conv_00000000000000000000000000000001"
        ],
        "created_at": "2026-10-05T12:00:00.000000Z",
        "expires_at": "2026-10-05T13:00:00.000000Z",
        "grant_id": "grant_fixture00000000000000000000000003",
        "host": "host-active",
        "last_used_at": null,
        "revoked_at": null,
        "scopes": [
          "board.split.decide"
        ],
        "status": "active",
        "use_count": 0
      },
      {
        "activated_at": null,
        "conversation_ids": [
          "conv_00000000000000000000000000000001"
        ],
        "created_at": "2026-10-05T12:00:00.000000Z",
        "expires_at": "2026-10-05T12:02:00.000000Z",
        "grant_id": "grant_fixture00000000000000000000000002",
        "host": "host-pending",
        "last_used_at": null,
        "revoked_at": null,
        "scopes": [
          "board.split.decide"
        ],
        "status": "pending",
        "use_count": 0
      },
      {
        "activated_at": "2026-10-05T12:00:00.000000Z",
        "conversation_ids": [
          "conv_00000000000000000000000000000001"
        ],
        "created_at": "2026-10-05T12:00:00.000000Z",
        "expires_at": "2026-10-05T13:00:00.000000Z",
        "grant_id": "grant_fixture00000000000000000000000001",
        "host": "claude-code",
        "last_used_at": "2026-10-05T12:00:00.000000Z",
        "revoked_at": null,
        "scopes": [
          "board.split.decide"
        ],
        "status": "active",
        "use_count": 1
      }
    ],
    "schema_version": "plugin_grant_list/v2"
  },
  "operator_revoke": {
    "grant": {
      "activated_at": null,
      "conversation_ids": [
        "conv_00000000000000000000000000000001"
      ],
      "created_at": "2026-10-05T12:00:00.000000Z",
      "expires_at": "2026-10-05T12:02:00.000000Z",
      "grant_id": "grant_fixture00000000000000000000000006",
      "host": "opencode",
      "last_used_at": null,
      "revoked_at": "2026-10-05T12:00:00.000000Z",
      "scopes": [
        "board.split.decide"
      ],
      "status": "revoked",
      "use_count": 0
    },
    "schema_version": "plugin_grant_revoke/v2"
  },
  "plugin_content_type_invalid": {
    "detail": {
      "code": "plugin_content_type_invalid",
      "correlation_id": null,
      "details": {},
      "field_errors": {},
      "message": "Plugin routes require a JSON body",
      "retryable": false
    }
  },
  "plugin_grant_invalid": {
    "detail": {
      "code": "plugin_grant_invalid",
      "correlation_id": null,
      "details": {},
      "field_errors": {},
      "message": "Plugin grant is missing or invalid",
      "retryable": false
    }
  },
  "plugin_origin_forbidden": {
    "detail": {
      "code": "plugin_origin_forbidden",
      "correlation_id": null,
      "details": {},
      "field_errors": {},
      "message": "Cross-origin plugin requests are forbidden",
      "retryable": false
    }
  },
  "plugin_pairing_invalid": {
    "detail": {
      "code": "plugin_pairing_invalid",
      "correlation_id": null,
      "details": {},
      "field_errors": {},
      "message": "Pairing code is missing or invalid",
      "retryable": false
    }
  },
  "plugin_pairing_locked": {
    "detail": {
      "code": "plugin_pairing_locked",
      "correlation_id": null,
      "details": {},
      "field_errors": {},
      "message": "Too many failed pairing attempts",
      "retryable": false
    }
  },
  "plugin_revoke": {
    "grant": {
      "activated_at": "2026-10-05T12:00:00.000000Z",
      "conversation_ids": [
        "conv_00000000000000000000000000000001"
      ],
      "created_at": "2026-10-05T12:00:00.000000Z",
      "expires_at": "2026-10-05T13:00:00.000000Z",
      "grant_id": "grant_fixture00000000000000000000000001",
      "host": "claude-code",
      "last_used_at": "2026-10-05T12:00:00.000000Z",
      "revoked_at": "2026-10-05T12:00:00.000000Z",
      "scopes": [
        "board.split.decide"
      ],
      "status": "revoked",
      "use_count": 1
    },
    "schema_version": "plugin_grant_revoke/v2"
  },
  "room_board_split_decided": {
    "detail": {
      "code": "room_board_split_decided",
      "correlation_id": null,
      "details": {},
      "field_errors": {},
      "message": "Board split was already decided",
      "retryable": false
    }
  },
  "room_board_split_digest_mismatch": {
    "detail": {
      "code": "room_board_split_digest_mismatch",
      "correlation_id": null,
      "details": {},
      "field_errors": {},
      "message": "Board split digest does not match",
      "retryable": false
    }
  },
  "room_board_split_not_proposed": {
    "detail": {
      "code": "room_board_split_not_proposed",
      "correlation_id": null,
      "details": {},
      "field_errors": {},
      "message": "Board split can no longer be decided",
      "retryable": false
    }
  }
};
