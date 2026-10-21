import { useState } from 'react'

function App() {
  const [message, setMessage] = useState("Not connected");
  const [loading, setLoading] = useState(false);

  async function checkBackend() {
    setLoading(true);

    try {
      const response = await fetch(
        "http://localhost:8000/api/health"
      );

      if (!response.ok) {
        throw new Error("Backend request failed");
      }

      const data = await response.json();
      setMessage(data.message);
    } catch (error) {
      console.error(error);
      setMessage("Could not connect to backend");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main>
      <h1>AI Interview Coach</h1>
      <p>Backend status: {message}</p>

      <button onClick={checkBackend} disabled={loading}>
        {loading ? "Connecting..." : "Check Backend"}
      </button>
    </main>
  );
}

export default App
