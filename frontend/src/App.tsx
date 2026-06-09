import { Routes, Route, Link } from "react-router-dom";
import HomePage from "./pages/HomePage";
import PoliticianPage from "./pages/PoliticianPage";
import OrganizationPage from "./pages/OrganizationPage";
import SearchPage from "./pages/SearchPage";
import AdminSourcesPage from "./pages/AdminSourcesPage";
import SearchBar from "./components/SearchBar";

export default function App() {
  return (
    <div className="min-h-screen">
      <header className="bg-blue-900 text-white p-3 sm:p-4">
        <div className="max-w-6xl mx-auto flex flex-col sm:flex-row sm:items-center sm:gap-4 gap-3">
          <div className="flex-1 min-w-0">
            <h1 className="text-lg sm:text-xl font-bold leading-tight">
              <Link to="/">Avanguardia Publica</Link>
            </h1>
            <p className="text-xs text-blue-200">Political Data Transparency</p>
          </div>
          <div className="w-full sm:w-auto">
            <SearchBar />
          </div>
        </div>
        <nav className="max-w-6xl mx-auto mt-2 flex gap-4 text-xs sm:text-sm">
          <Link to="/" className="hover:underline">Politicians</Link>
          <Link to="/search" className="hover:underline">Advanced Search</Link>
          <Link to="/admin/sources" className="hover:underline text-blue-200">Admin · Sources</Link>
        </nav>
      </header>
      <main className="max-w-6xl mx-auto p-3 sm:p-4">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/politician/:id" element={<PoliticianPage />} />
          <Route path="/organization/:id" element={<OrganizationPage />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/admin/sources" element={<AdminSourcesPage />} />
        </Routes>
      </main>
    </div>
  );
}
