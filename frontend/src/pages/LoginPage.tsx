/**
 * Login page — minimal centered form with brand colors and micro-interactions.
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

export default function LoginPage(): JSX.Element {
  const navigate = useNavigate();
  const setAuth = useAuthStore((s) => s.setAuth);

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const result = await authApi.login(email, password);
      setAuth(result.token, result.user);
      navigate("/");
    } catch (err: unknown) {
      setError(apiErrorMessage(err, "Sign in failed."));
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
              BandPilot
            </Typography>
            <Typography
              variant="body2"
              sx={{ color: palette.textSecondary, mt: 0.5 }}
            >
              Turn MIDI into playable professional band scores
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
              autoComplete="current-password"
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
                {loading ? "Signing in…" : "Sign In"}
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
            Don't have an account?{" "}
            <Link
              component={RouterLink}
              to="/register"
              sx={{
                color: palette.brandPrimary,
                fontWeight: 600,
                textDecoration: "none",
                "&:hover": { textDecoration: "underline" },
              }}
            >
              Register
            </Link>
          </Typography>
        </Box>
      </motion.div>
    </Box>
  );
}
