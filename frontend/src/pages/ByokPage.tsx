/**
 * BYOK page — configure and test LLM API key.
 *
 * Redesign:
 *  - Config status indicator (active / not configured).
 *  - Form with brand-colored inputs.
 *  - Test connection feedback with success/error states.
 */

import { useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  TextField,
  Typography,
} from "@mui/material";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import CancelIcon from "@mui/icons-material/Cancel";
import KeyIcon from "@mui/icons-material/VpnKey";
import { motion } from "framer-motion";
import { byokApi } from "../api/client";
import type { ByokResponse } from "../api/types";
import { palette } from "../styles/tokens";

export default function ByokPage(): JSX.Element {
  const [config, setConfig] = useState<ByokResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<{
    ok: boolean;
    message: string;
  } | null>(null);

  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [provider, setProvider] = useState("openai_compatible");

  useEffect(() => {
    void loadConfig();
  }, []);

  async function loadConfig(): Promise<void> {
    setLoading(true);
    try {
      const data = await byokApi.get();
      setConfig(data);
      if (data) {
        setProvider(data.provider);
        setBaseUrl(data.base_url ?? "");
        setModel(data.model ?? "");
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  async function handleSave(): Promise<void> {
    setSaving(true);
    setError(null);
    setSuccess(null);
    setTestResult(null);
    try {
      const data = await byokApi.save({
        provider,
        api_key: apiKey,
        base_url: baseUrl || null,
        model: model || null,
      });
      setConfig(data);
      setSuccess("BYOK configuration saved successfully.");
      setApiKey("");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function handleTest(): Promise<void> {
    setTesting(true);
    setError(null);
    setSuccess(null);
    setTestResult(null);
    try {
      const result = await byokApi.test({
        provider,
        api_key: apiKey,
        base_url: baseUrl || null,
        model: model || null,
      });
      setTestResult({ ok: result.ok, message: result.message });
    } catch (err) {
      setTestResult({
        ok: false,
        message: (err as Error).message,
      });
    } finally {
      setTesting(false);
    }
  }

  async function handleDelete(): Promise<void> {
    try {
      await byokApi.remove();
      setConfig(null);
      setTestResult(null);
      setSuccess("BYOK configuration deleted.");
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <Box className="flex flex-col gap-6">
      <Box
        className="rounded-2xl px-6 py-7"
        sx={{
          background: `linear-gradient(135deg, ${palette.elevated} 0%, ${palette.surface} 100%)`,
          border: `1px solid ${palette.borderDefault}`,
        }}
      >
        <Box className="flex items-center gap-2.5 mb-2">
          <Box
            sx={{
              width: 32,
              height: 32,
              borderRadius: 2,
              backgroundColor: `${palette.brandPrimary}15`,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <KeyIcon sx={{ color: palette.brandPrimary, fontSize: 18 }} />
          </Box>
          <Typography variant="h5" fontWeight={700} sx={{ color: palette.textPrimary, letterSpacing: "-0.01em" }}>
            LLM Settings
          </Typography>
        </Box>
        <Typography variant="body2" sx={{ color: palette.textSecondary, lineHeight: 1.6, maxWidth: 520 }}>
          Configure your own LLM API key to enable AI-driven note rewrite.
          Without a key, FretPilot runs in degraded (rule-based) mode.
        </Typography>
      </Box>

      {loading ? (
        <Box className="flex items-center gap-3 py-8">
          <CircularProgress size={24} />
          <Typography sx={{ color: palette.textSecondary }}>
            Loading configuration…
          </Typography>
        </Box>
      ) : (
        <>
          {/* ── Status indicator ── */}
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25 }}
          >
            <Box
              className="rounded-xl p-4 flex items-center gap-3"
              sx={{
                backgroundColor: config
                  ? `${palette.success}10`
                  : `${palette.warning}10`,
                border: `1px solid ${config ? `${palette.success}40` : `${palette.warning}40`}`,
              }}
            >
              {config ? (
                <CheckCircleIcon sx={{ color: palette.success, fontSize: 28 }} />
              ) : (
                <CancelIcon sx={{ color: palette.warning, fontSize: 28 }} />
              )}
              <Box className="flex-1">
                <Typography
                  variant="subtitle1"
                  fontWeight={600}
                  sx={{
                    color: config
                      ? palette.success
                      : palette.warning,
                  }}
                >
                  {config ? "LLM Key Active" : "Not Configured"}
                </Typography>
                <Typography
                  variant="body2"
                  sx={{ color: palette.textSecondary }}
                >
                  {config
                    ? `Provider: ${config.provider} · Key: ${config.key_masked}`
                    : "FretPilot is running in degraded (rule-based) mode."}
                </Typography>
              </Box>
              {config && (
                <Box className="flex gap-2 flex-wrap">
                  {config.base_url && (
                    <Chip
                      size="small"
                      label={config.base_url}
                      sx={{
                        backgroundColor: palette.subtle,
                        color: palette.textSecondary,
                        border: "none",
                      }}
                    />
                  )}
                  {config.model && (
                    <Chip
                      size="small"
                      label={config.model}
                      sx={{
                        backgroundColor: palette.subtle,
                        color: palette.textSecondary,
                        border: "none",
                      }}
                    />
                  )}
                </Box>
              )}
            </Box>
          </motion.div>

          {error && (
            <Alert severity="error" sx={{ borderRadius: 2 }}>
              {error}
            </Alert>
          )}
          {success && (
            <Alert severity="success" sx={{ borderRadius: 2 }}>
              {success}
            </Alert>
          )}

          {/* ── Test connection feedback ── */}
          {testResult && (
            <motion.div
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.2 }}
            >
              <Alert
                severity={testResult.ok ? "success" : "error"}
                sx={{ borderRadius: 2 }}
              >
                {testResult.message}
              </Alert>
            </motion.div>
          )}

          {/* ── Configuration form ── */}
          <Box
            className="rounded-xl p-5"
            sx={{
              backgroundColor: palette.elevated,
              border: `1px solid ${palette.borderDefault}`,
            }}
          >
            <Box className="flex items-center gap-2 mb-4">
              <KeyIcon sx={{ color: palette.brandPrimary, fontSize: 20 }} />
              <Typography
                variant="h6"
                fontWeight={600}
                sx={{ color: palette.textPrimary }}
              >
                Configuration
              </Typography>
            </Box>
            <Box sx={{ display: "flex", flexDirection: "column", gap: 2.5 }}>
              <TextField
                label="Provider"
                value={provider}
                onChange={(e) => setProvider(e.target.value)}
                fullWidth
                helperText="Currently only 'openai_compatible' is supported"
              />
              <TextField
                label="API Key"
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                fullWidth
                placeholder={config ? "Enter new key to replace" : "sk-..."}
              />
              <TextField
                label="Base URL (optional)"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                fullWidth
                placeholder="https://api.openai.com/v1"
              />
              <TextField
                label="Model (optional)"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                fullWidth
                placeholder="gpt-4o-mini"
              />
              <Box className="flex gap-2 mt-2">
                <Button
                  variant="contained"
                  onClick={handleSave}
                  disabled={saving || !apiKey}
                  sx={{
                    textTransform: "none",
                    backgroundColor: palette.brandPrimary,
                    "&:hover": { backgroundColor: palette.brandHover },
                  }}
                >
                  {saving ? "Saving…" : "Save"}
                </Button>
                <Button
                  variant="outlined"
                  onClick={handleTest}
                  disabled={testing || !apiKey}
                  startIcon={
                    testing ? (
                      <CircularProgress size={16} color="inherit" />
                    ) : undefined
                  }
                  sx={{
                    textTransform: "none",
                    borderColor: palette.borderDefault,
                    color: palette.textPrimary,
                    "&:hover": {
                      borderColor: palette.brandPrimary,
                      backgroundColor: "rgba(232, 162, 75, 0.06)",
                    },
                  }}
                >
                  {testing ? "Testing…" : "Test Connection"}
                </Button>
                {config && (
                  <Button
                    variant="outlined"
                    color="error"
                    onClick={handleDelete}
                    sx={{
                      textTransform: "none",
                      borderColor: palette.error,
                      color: palette.error,
                      "&:hover": {
                        backgroundColor: "rgba(248, 113, 113, 0.06)",
                      },
                    }}
                  >
                    Delete
                  </Button>
                )}
              </Box>
            </Box>
          </Box>
        </>
      )}
    </Box>
  );
}
