import { useState } from "react";
import { Link as RouterLink, useNavigate } from "react-router-dom";
import { Alert, Box, Button, Link, TextField, Typography } from "@mui/material";
import AuthShell from "../components/AuthShell";
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

  const handleSubmit = async (event: React.FormEvent): Promise<void> => {
    event.preventDefault(); setLoading(true); setError(null);
    try { const result = await authApi.login(email, password); setAuth(result.token, result.user); navigate("/"); }
    catch (err: unknown) { setError(apiErrorMessage(err, "We couldn’t sign you in. Check your details and try again.")); }
    finally { setLoading(false); }
  };

  return (
    <AuthShell title="Welcome back" description="Sign in to continue working on your scores."
      footer={<Typography sx={{ color: palette.textSecondary, fontSize: 13 }}>New to BandPilot? <Link component={RouterLink} to="/register" sx={{ color: palette.brandPrimary, fontWeight: 750, textDecoration: "none" }}>Create an account</Link></Typography>}>
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      <Box component="form" onSubmit={handleSubmit} className="flex flex-col gap-4">
        <TextField label="Email" type="email" value={email} onChange={(event) => setEmail(event.target.value)} required fullWidth autoComplete="email" />
        <TextField label="Password" type="password" value={password} onChange={(event) => setPassword(event.target.value)} required fullWidth autoComplete="current-password" />
        <Button type="submit" variant="contained" size="large" disabled={loading} fullWidth sx={{ mt: 1, minHeight: 48 }}>{loading ? "Signing in…" : "Sign in"}</Button>
      </Box>
    </AuthShell>
  );
}
