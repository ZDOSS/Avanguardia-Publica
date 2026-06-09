import { Routes, Route, Link } from "react-router-dom";
import HomePage from "./pages/HomePage";
import PoliticianPage from "./pages/PoliticianPage";
import OrganizationPage from "./pages/OrganizationPage";

export default function App() {
  return (
    <div className="min-h-screen">
      <header className="bg-blue-900 text-white p-4">
        <div className="max-w-6xl mx-auto">
          <h1 className="text-xl font-bold">
            <Link to="/">Avanguardia Publica</Link>
          </h1>
          <p className="text-sm text-blue-200">Political Data Transparency</p>
        </div>
      </header>
      <main className="max-w-6xl mx-auto p-4">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/politician/:id" element={<PoliticianPage />} />
          <Route path="/organization/:id" element={<OrganizationPage />} />
        </Routes>
      </main>
    </div>
  );
}
