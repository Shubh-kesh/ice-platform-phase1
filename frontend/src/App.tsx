import { Routes, Route } from "react-router-dom";
import { Login } from "./pages/Login";
import { GoogleCallback } from "./pages/GoogleCallback";
import { CommandCenter } from "./pages/CommandCenter";
import { ProjectDetail } from "./pages/ProjectDetail";
import { Assistant } from "./pages/Assistant";
import { ProtectedRoute } from "./components/ProtectedRoute";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      {/* Google OAuth redirect target (public): completes the flow started by
          the backend authorize endpoint and stores a normal ICE session. */}
      <Route path="/google/callback" element={<GoogleCallback />} />
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <CommandCenter />
          </ProtectedRoute>
        }
      />
      <Route
        path="/projects/:projectId"
        element={
          <ProtectedRoute>
            <ProjectDetail />
          </ProtectedRoute>
        }
      />
      <Route
        path="/assistant"
        element={
          <ProtectedRoute>
            <Assistant />
          </ProtectedRoute>
        }
      />
    </Routes>
  );
}
