import { useState } from "react";
import { Link as RouterLink, useNavigate } from "react-router-dom";
import { Alert, Box, Button, Link, TextField, Typography } from "@mui/material";
import AuthShell from "../components/AuthShell";
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

  const handleSubmit = async (event: React.FormEvent): Promise<void> => {
    event.preventDefault();
    if (password !== confirm) { setError("Passwords don’t match."); return; }
    setLoading(true); setError(null);
    try { const result = await authApi.register(email, password); setAuth(result.token, result.user); navigate("/"); }
    catch (err: unknown) { setError(apiErrorMessage(err, "We couldn’t create your account.")); }
    finally { setLoading(false); }
  };

  return (
    <AuthShell title="Create your workspace" description="Import your first MIDI and turn it into a practical band score."
      footer={<Typography sx={{ color: palette.textSecondary, fontSize: 13 }}>Already have an account? <Link component={RouterLink} to="/login" sx={{ color: palette.brandPrimary, fontWeight: 750, textDecoration: "none" }}>Sign in</Link></Typography>}>
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      <Box component="form" onSubmit={handleSubmit} className="flex flex-col gap-4">
        <TextField label="Email" type="email" value={email} onChange={(event) => setEmail(event.target.value)} required fullWidth autoComplete="email" />
        <TextField label="Password" type="password" value={password} onChange={(event) => setPassword(event.target.value)} required fullWidth helperText="At least 6 characters" autoComplete="new-password" />
        <TextField label="Confirm password" type="password" value={confirm} onChange={(event) => setConfirm(event.target.value)} required fullWidth autoComplete="new-password" />
        <Button type="submit" variant="contained" size="large" disabled={loading} fullWidth sx={{ mt: 1, minHeight: 48 }}>{loading ? "Creating workspace…" : "Create account"}</Button>
      </Box>
    </AuthShell>
  );
}
