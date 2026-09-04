import { Routes, Route } from "react-router-dom";
import { LandingPage } from "./pages/LandingPage";
import { JoinByCodePage } from "./pages/JoinByCodePage";
import { PreflightPage } from "./pages/PreflightPage";
import { ConsentPage } from "./pages/ConsentPage";
import { BiometricPage } from "./pages/BiometricPage";
import { RolePickerPage } from "./pages/RolePickerPage";
import { LobbyPage } from "./pages/LobbyPage";
import { TaskPage } from "./pages/TaskPage";
import { RunShellPage } from "./pages/RunShellPage";
import { ResumePage } from "./pages/ResumePage";
import { FinishPage } from "./pages/FinishPage";
import { SetupPage } from "./pages/SetupPage";

function NotFound() {
  return <div style={{ padding: 24 }}>Not found</div>;
}

export function App() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/s/:code" element={<JoinByCodePage />} />
      <Route path="/p/preflight/:code" element={<PreflightPage />} />
      <Route path="/p/consent" element={<ConsentPage />} />
      <Route path="/p/biometric" element={<BiometricPage />} />
      <Route path="/p/run" element={<RunShellPage />} />
      <Route path="/p/resume" element={<ResumePage />} />
      <Route path="/p/role" element={<RolePickerPage />} />
      <Route path="/p/lobby" element={<LobbyPage />} />
      <Route path="/p/task" element={<TaskPage />} />
      <Route path="/p/finish" element={<FinishPage />} />
      <Route path="/setup" element={<SetupPage />} />
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}
