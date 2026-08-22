/**
 * Layout shell — sidebar navigation (对标 Linear/Notion).
 *
 * 左侧 240px sidebar：logo + nav + user/settings 底部
 * 右侧主内容区：max-width 自适应，padding 32px
 * 移动端：bottom drawer
 */

import { type ReactNode, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  Box,
  IconButton,
  Tooltip,
  Avatar,
} from "@mui/material";
import MusicNoteIcon from "@mui/icons-material/MusicNote";
import UploadIcon from "@mui/icons-material/UploadFile";
import SchoolIcon from "@mui/icons-material/School";
import SettingsIcon from "@mui/icons-material/Settings";
import LogoutIcon from "@mui/icons-material/Logout";
import MenuIcon from "@mui/icons-material/Menu";
import CloseIcon from "@mui/icons-material/Close";
import { useAuthStore } from "../store/auth";
import { palette } from "../styles/tokens";

interface LayoutProps {
  children: ReactNode;
}

interface NavItem {
  label: string;
  path: string;
  icon: ReactNode;
}

const NAV_ITEMS: NavItem[] = [
  { label: "Import", path: "/", icon: <UploadIcon fontSize="small" /> },
  { label: "Learning", path: "/learning", icon: <SchoolIcon fontSize="small" /> },
  { label: "Settings", path: "/settings", icon: <SettingsIcon fontSize="small" /> },
];

export default function Layout({ children }: LayoutProps): JSX.Element {
  const location = useLocation();
  const navigate = useNavigate();
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const [mobileOpen, setMobileOpen] = useState(false);

  const isActivePath = (path: string): boolean => {
    if (path === "/") return location.pathname === "/" || location.pathname.startsWith("/projects");
    if (path === "/settings") return location.pathname === "/settings" || location.pathname === "/byok";
    return location.pathname.startsWith(path);
  };

  const handleLogout = (): void => {
    logout();
    navigate("/login");
  };

  const sidebarContent = (
    <Box
      className="flex flex-col h-full"
      sx={{ backgroundColor: palette.canvas }}
    >
      {/* Logo */}
      <Box
        className="flex items-center gap-2.5 px-5"
        sx={{ height: 56, flexShrink: 0 }}
      >
        <Box
          sx={{
            width: 32,
            height: 32,
            borderRadius: 2,
            backgroundColor: `${palette.brandPrimary}18`,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <MusicNoteIcon sx={{ color: palette.brandPrimary, fontSize: 20 }} />
        </Box>
        <Box className="flex flex-col">
          <span
            className="font-bold text-base"
            style={{ color: palette.textPrimary, letterSpacing: "-0.01em", lineHeight: 1.1 }}
          >
            BandPilot
          </span>
          <span
            className="text-[10px] font-medium"
            style={{ color: palette.textTertiary, letterSpacing: "0.02em" }}
          >
            Guitar + Drums
          </span>
        </Box>
      </Box>

      {/* Nav */}
      <Box className="flex-1 px-3 py-4 flex flex-col gap-0.5">
        {NAV_ITEMS.map((item) => {
          const active = isActivePath(item.path);
          return (
            <Link
              key={item.path}
              to={item.path}
              onClick={() => setMobileOpen(false)}
              className="flex items-center gap-3 px-3 py-2 rounded-lg no-underline transition-all"
              style={{
                color: active ? palette.brandPrimary : palette.textSecondary,
                fontWeight: active ? 600 : 500,
                fontSize: 14,
                backgroundColor: active ? `${palette.brandPrimary}12` : "transparent",
              }}
            >
              {item.icon}
              {item.label}
            </Link>
          );
        })}
      </Box>

      {/* User + logout */}
      {isAuthenticated && user && (
        <Box
          className="px-3 py-3 flex items-center gap-2"
          sx={{ borderTop: `1px solid ${palette.borderDefault}`, flexShrink: 0 }}
        >
          <Avatar
            sx={{
              width: 28,
              height: 28,
              fontSize: 13,
              bgcolor: palette.subtle,
              color: palette.textSecondary,
            }}
          >
            {user.email[0]?.toUpperCase()}
          </Avatar>
          <Box className="flex-1 min-w-0">
            <Box
              className="text-xs truncate"
              style={{ color: palette.textSecondary }}
            >
              {user.email}
            </Box>
          </Box>
          <Tooltip title="Logout">
            <IconButton
              size="small"
              onClick={handleLogout}
              sx={{ color: palette.textTertiary, "&:hover": { color: palette.error } }}
            >
              <LogoutIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        </Box>
      )}
    </Box>
  );

  return (
    <Box className="flex h-screen" sx={{ backgroundColor: palette.surface }}>
      {/* Desktop sidebar */}
      <Box
        component="nav"
        className="hidden md:block flex-shrink-0"
        sx={{ width: 240, borderRight: `1px solid ${palette.borderDefault}` }}
      >
        {sidebarContent}
      </Box>

      {/* Mobile sidebar */}
      {mobileOpen && (
        <Box
          className="md:hidden fixed inset-0 z-50 flex"
          onClick={() => setMobileOpen(false)}
        >
          <Box sx={{ position: "absolute", inset: 0, backgroundColor: "rgba(0,0,0,0.5)" }} />
          <Box
            sx={{
              width: 240,
              height: "100%",
              position: "relative",
              borderRight: `1px solid ${palette.borderDefault}`,
            }}
            onClick={(e) => e.stopPropagation()}
          >
            {sidebarContent}
          </Box>
        </Box>
      )}

      {/* Main content */}
      <Box className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Mobile header */}
        <Box
          className="md:hidden flex items-center px-4"
          sx={{
            height: 48,
            backgroundColor: palette.canvas,
            borderBottom: `1px solid ${palette.borderDefault}`,
            flexShrink: 0,
          }}
        >
          <IconButton size="small" onClick={() => setMobileOpen(true)} sx={{ color: palette.textPrimary }}>
            {mobileOpen ? <CloseIcon fontSize="small" /> : <MenuIcon fontSize="small" />}
          </IconButton>
          <span className="ml-2 font-bold text-sm" style={{ color: palette.textPrimary }}>
            BandPilot
          </span>
        </Box>

        {/* Scrollable content */}
        <Box className="flex-1 overflow-y-auto">
          <Box sx={{ maxWidth: 1400, mx: "auto", px: { xs: 3, md: 5 }, py: { xs: 4, md: 6 } }}>
            {children}
          </Box>
        </Box>
      </Box>
    </Box>
  );
}
