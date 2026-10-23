import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import ProtectedRoute from './components/auth/ProtectedRoute'
import AppLayout from './components/layout/AppLayout'
import AuthProvider from './context/AuthProvider'
import AuthPage from './pages/AuthPage'
import PracticePage from './pages/PracticePage'
import RecordingPage from './pages/RecordingPage'
import ReviewPage from './pages/ReviewPage'
import DashboardPage from './pages/DashboardPage'
import HistoryPage from './pages/HistoryPage'
import ComparePage from './pages/ComparePage'
import ProgressPage from './pages/ProgressPage'

// Temporary page, replaced one by one in later steps.
function Placeholder({ title }: { title: string }) {
  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
      <p className="mt-2 text-muted">This page is coming soon.</p>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<AuthPage mode="login" />} />
          <Route path="/register" element={<AuthPage mode="register" />} />

          <Route element={<ProtectedRoute />}>
            <Route element={<AppLayout />}>
              <Route index element={<Navigate to="/dashboard" replace />} />
              <Route path="/dashboard" element={<DashboardPage />} />
              <Route path="/practice" element={<PracticePage />} />
              {/* <Route path="/record/:sessionId" element={<Placeholder title="Recording room" />} /> */}
              <Route path="/record/:sessionId" element={<RecordingPage />} />
              <Route path="/review/:sessionId" element={<ReviewPage />} />
              <Route path="/history" element={<HistoryPage />} />
              <Route path="/compare/:sessionId" element={<ComparePage />} />
              <Route path="/progress" element={<ProgressPage />} />
              <Route path="*" element={<Placeholder title="Page not found" />} />
            </Route>
          </Route>
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  )
}