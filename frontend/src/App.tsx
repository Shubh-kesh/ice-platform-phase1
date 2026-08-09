import { Routes, Route } from "react-router-dom";
import { Login } from "./pages/Login";
import { CommandCenter } from "./pages/CommandCenter";
import { ProjectDetail } from "./pages/ProjectDetail";
import { ProtectedRoute } from "./components/ProtectedRoute";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
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
    </Routes>
  );
}
