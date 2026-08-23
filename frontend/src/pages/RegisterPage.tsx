/**
 * Register page — create a new account.
 * Consistent with LoginPage styling.
 */

import { useState } from "react";
import { useNavigate, Link as RouterLink } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Link,
  TextField,
  Typography,
} from "@mui/material";
import { MusicNoteIcon } from "../icons";
import { motion } from "framer-motion";
import { authApi } from "../api/client";
import { useAuthStore } from "../store/auth";
import { palette } from "../styles/tokens";
import { apiErrorMessage } from "../utils/apiError";

export default function RegisterPage(): JSX.Element {
  const navigate = useNavigate();
  const setAuth = useAuthStore((s) => s.setAuth);

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const result = await authApi.register(email, password);
      setAuth(result.token, result.user);
      navigate("/");
    } catch (err: unknown) {
      setError(apiErrorMessage(err, "Account registration failed."));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Box
      className="min-h-screen flex items-center justify-center px-4"
      sx={{ backgroundColor: palette.surface }}
    >
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, ease: "easeOut" }}
        className="w-full"
        style={{ maxWidth: 400 }}
      >
        <Box
          className="rounded-2xl p-8"
          sx={{
            backgroundColor: palette.canvas,
            border: `1px solid ${palette.borderDefault}`,
            boxShadow: "0 4px 24px rgba(0, 0, 0, 0.06)",
          }}
        >
          {/* Logo + title */}
          <Box className="flex flex-col items-center mb-6">
            <Box
              className="flex items-center justify-center mb-3"
              sx={{
                width: 48,
                height: 48,
                borderRadius: 2,
                backgroundColor: `${palette.brandPrimary}15`,
              }}
            >
              <MusicNoteIcon
                sx={{ color: palette.brandPrimary, fontSize: 28 }}
              />
            </Box>
            <Typography
              variant="h5"
              fontWeight={700}
              sx={{ color: palette.textPrimary }}
            >
              Create Account
            </Typography>
            <Typography
              variant="body2"
              sx={{ color: palette.textSecondary, mt: 0.5 }}
            >
              Start building playable scores from full-band MIDI
            </Typography>
          </Box>

          {error && (
            <Alert
              severity="error"
              sx={{ mb: 2, borderRadius: 2, fontSize: "0.85rem" }}
            >
              {error}
            </Alert>
          )}

          <Box
            component="form"
            onSubmit={handleSubmit}
            sx={{ display: "flex", flexDirection: "column", gap: 2 }}
          >
            <TextField
              label="Email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              fullWidth
              autoComplete="email"
            />
            <TextField
              label="Password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              fullWidth
              helperText="At least 6 characters"
            />
            <TextField
              label="Confirm Password"
              type="password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              required
              fullWidth
            />
            <motion.div whileHover={{ scale: loading ? 1 : 1.01 }}>
              <Button
                type="submit"
                variant="contained"
                size="large"
                disabled={loading}
                fullWidth
                sx={{
                  textTransform: "none",
                  backgroundColor: palette.brandPrimary,
                  "&:hover": { backgroundColor: palette.brandHover },
                  py: 1.2,
                }}
              >
                {loading ? "Creating account…" : "Register"}
              </Button>
            </motion.div>
          </Box>

          <Typography
            variant="body2"
            sx={{
              mt: 3,
              textAlign: "center",
              color: palette.textSecondary,
            }}
          >
            Already have an account?{" "}
            <Link
              component={RouterLink}
              to="/login"
              sx={{
                color: palette.brandPrimary,
                fontWeight: 600,
                textDecoration: "none",
                "&:hover": { textDecoration: "underline" },
              }}
            >
              Sign In
            </Link>
          </Typography>
        </Box>
      </motion.div>
    </Box>
  );
}
