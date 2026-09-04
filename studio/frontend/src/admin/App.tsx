import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AdminShell } from "./components/AdminShell";
import { useAdminSession } from "./hooks/useAdminSession";
import { ApiAccessPage } from "./pages/ApiAccessPage";
import { AuditPage } from "./pages/AuditPage";
import { ComparePage } from "./pages/ComparePage";
import { DashboardPage } from "./pages/DashboardPage";
import { FunnelPage } from "./pages/FunnelPage";
import { IrrPage } from "./pages/IrrPage";
import { LibraryPage } from "./pages/LibraryPage";
import { LoginPage } from "./pages/LoginPage";
import { NewStudyPage } from "./pages/NewStudyPage";
import { ParticipantJourneyPage } from "./pages/ParticipantJourneyPage";
import { ReplayPage } from "./pages/ReplayPage";
import { SessionDetailPage } from "./pages/SessionDetailPage";
import { SessionLivePage } from "./pages/SessionLivePage";
import { SessionsPage } from "./pages/SessionsPage";
import { SharedReplayPage } from "./pages/SharedReplayPage";
import { StudyDetailPage } from "./pages/StudyDetailPage";
import { StudyYamlPage } from "./pages/StudyYamlPage";
import { TaskDrilldownPage } from "./pages/TaskDrilldownPage";
import { UsersPage } from "./pages/UsersPage";
import { WebhooksPage } from "./pages/WebhooksPage";

function NotFound() {
  return <div style={{ padding: 24 }}>Not found</div>;
}

export function App() {
  const { username, loading, refresh } = useAdminSession();
  const location = useLocation();
  if (location.pathname.startsWith("/shared/")) {
    return (
      <Routes>
        <Route path="/shared/:token" element={<SharedReplayPage />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    );
  }

  if (loading) return null;

  if (!username) {
    if (location.pathname !== "/login") return <Navigate to="/login" replace />;
    return <LoginPage onLoggedIn={refresh} />;
  }
  if (location.pathname === "/login") return <Navigate to="/" replace />;

  return (
    <AdminShell>
      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/studies/new" element={<NewStudyPage />} />
        <Route path="/library" element={<LibraryPage />} />
        {/* Legacy bookmark alias for the old task-only library. */}
        <Route path="/tasks" element={<LibraryPage />} />
        <Route path="/studies/:slug" element={<StudyDetailPage />} />
        <Route path="/studies/:slug/yaml" element={<StudyYamlPage />} />
        <Route path="/studies/:slug/funnel" element={<FunnelPage />} />
        <Route path="/studies/:slug/task/:taskId" element={<TaskDrilldownPage />} />
        <Route path="/sessions" element={<SessionsPage />} />
        <Route path="/sessions/:id" element={<SessionDetailPage />} />
        <Route path="/sessions/:id/live" element={<SessionLivePage />} />
        <Route path="/replay/:id" element={<ReplayPage />} />
        <Route path="/participants/:id" element={<ParticipantJourneyPage />} />
        <Route path="/compare" element={<ComparePage />} />
        <Route path="/irr" element={<IrrPage />} />
        <Route path="/webhooks" element={<WebhooksPage />} />
        <Route path="/api-access" element={<ApiAccessPage />} />
        <Route path="/users" element={<UsersPage />} />
        <Route path="/audit" element={<AuditPage />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </AdminShell>
  );
}
