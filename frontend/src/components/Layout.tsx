import { type ReactNode, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Avatar, Box, IconButton, Tooltip, Typography } from "@mui/material";
import { CloseIcon, LogoutIcon, MenuIcon, MusicNoteIcon, SettingsIcon, UploadFileIcon } from "../icons";
import { useAuthStore } from "../store/auth";
import { palette } from "../styles/tokens";

interface LayoutProps { children: ReactNode }
interface NavItem { label: string; path: string; icon: ReactNode; helper?: string }

const PRIMARY_NAV: NavItem[] = [
  { label: "My music", path: "/", icon: <MusicNoteIcon fontSize="small" />, helper: "Projects & new score" },
];
const SECONDARY_NAV: NavItem[] = [
  { label: "AI settings", path: "/settings", icon: <SettingsIcon fontSize="small" /> },
];

export default function Layout({ children }: LayoutProps): JSX.Element {
  const location = useLocation();
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const [mobileOpen, setMobileOpen] = useState(false);
  const isEditor = /^\/projects\/\d+\/editor\/?$/.test(location.pathname);

  const isActive = (path: string): boolean => path === "/"
    ? location.pathname === "/" || location.pathname.startsWith("/projects")
    : location.pathname.startsWith(path);
  const handleLogout = (): void => { logout(); navigate("/login"); };

  // The editor is a focused desktop application, not a page inside the
  // marketing/workspace shell. Its own track rail and project bar replace the
  // global navigation so the score can own the available viewport.
  if (isEditor) {
    return (
      <Box className="h-screen min-w-0 overflow-hidden" sx={{ backgroundColor: palette.canvas }}>
        {children}
      </Box>
    );
  }

  const renderLink = (item: NavItem): JSX.Element => {
    const active = isActive(item.path);
    return (
      <Link key={item.path} to={item.path} onClick={() => setMobileOpen(false)} className="flex items-center gap-3 no-underline"
        style={{ color: active ? "#FFFFFF" : "#A9ADB5", background: active ? "rgba(255,255,255,.10)" : "transparent", borderRadius: 12, padding: "10px 12px", transition: "background .15s ease, color .15s ease" }}>
        <Box sx={{ color: active ? "#F4A261" : "#777D87", display: "flex" }}>{item.icon}</Box>
        <Box className="min-w-0">
          <Typography sx={{ fontSize: 13, lineHeight: 1.25, fontWeight: active ? 700 : 600 }}>{item.label}</Typography>
          {item.helper && <Typography sx={{ color: "#646A74", fontSize: 10, mt: 0.25 }}>{item.helper}</Typography>}
        </Box>
      </Link>
    );
  };

  const sidebar = (
    <Box className="flex flex-col h-full" sx={{ background: "#12151B", color: "#fff" }}>
      <Box className="flex items-center gap-3 px-5" sx={{ height: 72 }}>
        <Box className="flex items-center justify-center" sx={{ width: 34, height: 34, borderRadius: 2.5, background: palette.brandPrimary }}><MusicNoteIcon sx={{ color: "#fff", fontSize: 20 }} /></Box>
        <Box><Typography sx={{ color: "#fff", fontWeight: 800, fontSize: 16, letterSpacing: "-.02em" }}>BandPilot</Typography><Typography sx={{ color: "#646A74", fontSize: 10 }}>Playable by design</Typography></Box>
      </Box>
      <Box className="px-3 pt-3">
        <Link to="/" onClick={() => setMobileOpen(false)} className="flex items-center justify-center gap-2 no-underline"
          style={{ background: palette.brandPrimary, color: "#fff", borderRadius: 11, minHeight: 42, fontSize: 13, fontWeight: 800 }}>
          <UploadFileIcon sx={{ fontSize: 18 }} /> New score
        </Link>
      </Box>
      <Box className="flex-1 px-3 pt-6 flex flex-col gap-1">
        <Typography className="px-3" sx={{ color: "#555B65", fontSize: 10, fontWeight: 800, letterSpacing: ".12em", textTransform: "uppercase", mb: 1 }}>Workspace</Typography>
        {PRIMARY_NAV.map(renderLink)}
      </Box>
      <Box className="px-3 pb-3 flex flex-col gap-1">
        <Typography className="px-3" sx={{ color: "#555B65", fontSize: 10, fontWeight: 800, letterSpacing: ".12em", textTransform: "uppercase", mb: 1 }}>Support</Typography>
        {SECONDARY_NAV.map(renderLink)}
      </Box>
      {user && (
        <Box className="px-4 py-4 flex items-center gap-2" sx={{ borderTop: "1px solid rgba(255,255,255,.07)" }}>
          <Avatar sx={{ width: 30, height: 30, bgcolor: "#292E37", color: "#D6D8DC", fontSize: 12 }}>{user.email[0]?.toUpperCase()}</Avatar>
          <Typography className="truncate flex-1" sx={{ color: "#8D929B", fontSize: 11 }}>{user.email}</Typography>
          <Tooltip title="Sign out"><IconButton size="small" onClick={handleLogout} sx={{ color: "#686E78", "&:hover": { color: "#fff" } }}><LogoutIcon fontSize="small" /></IconButton></Tooltip>
        </Box>
      )}
    </Box>
  );

  return (
    <Box className="flex h-screen" sx={{ backgroundColor: palette.canvas }}>
      <Box component="nav" className="hidden md:block flex-shrink-0" sx={{ width: 216 }}>{sidebar}</Box>
      {mobileOpen && (
        <Box className="md:hidden fixed inset-0 z-50 flex" onClick={() => setMobileOpen(false)}>
          <Box sx={{ position: "absolute", inset: 0, background: "rgba(18,21,27,.56)", backdropFilter: "blur(4px)" }} />
          <Box sx={{ width: 250, height: "100%", position: "relative" }} onClick={(event) => event.stopPropagation()}>{sidebar}</Box>
        </Box>
      )}
      <Box className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <Box className="md:hidden flex items-center justify-between px-4" sx={{ height: 56, background: "#12151B" }}>
          <Box className="flex items-center gap-2"><MusicNoteIcon sx={{ color: palette.brandPrimary }} /><Typography sx={{ color: "#fff", fontWeight: 800 }}>BandPilot</Typography></Box>
          <IconButton onClick={() => setMobileOpen((open) => !open)} sx={{ color: "#fff" }}>{mobileOpen ? <CloseIcon /> : <MenuIcon />}</IconButton>
        </Box>
        <Box className="flex-1 overflow-y-auto">
          <Box sx={{ maxWidth: 1240, mx: "auto", px: { xs: 2.5, sm: 4, lg: 6 }, py: { xs: 4, lg: 5 } }}>
            {children}
          </Box>
        </Box>
      </Box>
    </Box>
  );
}
