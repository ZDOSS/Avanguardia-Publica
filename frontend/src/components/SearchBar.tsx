import { useState, useRef, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { searchAll, type SearchResultItem } from "../lib/api";

export default function SearchBar() {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const containerRef = useRef<HTMLDivElement>(null);

  const { data } = useQuery({
    queryKey: ["search", query],
    queryFn: () => searchAll(query, 8),
    enabled: query.length >= 2,
    staleTime: 30_000,
  });

  useEffect(() => {
    function handleClick(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (query.trim().length >= 2) {
      navigate(`/search?q=${encodeURIComponent(query.trim())}`);
      setOpen(false);
    }
  }

  function handleSelect(item: SearchResultItem) {
    if (item.url) {
      navigate(item.url);
      setOpen(false);
      setQuery("");
    }
  }

  return (
    <div ref={containerRef} className="relative w-full sm:w-72">
      <form onSubmit={handleSubmit}>
        <input
          type="search"
          placeholder="Search politicians, orgs, bills, donors..."
          aria-label="Search"
          className="w-full border rounded px-3 py-1.5 text-sm text-gray-900"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
        />
      </form>
      {open && query.length >= 2 && data && data.items.length > 0 && (
        <ul className="absolute top-full left-0 right-0 mt-1 bg-white border rounded shadow-lg z-50 max-h-80 overflow-auto text-sm text-gray-900">
          {data.items.map((item) => (
            <li
              key={`${item.entity_type}:${item.entity_id}`}
              className="px-3 py-2 hover:bg-blue-50 cursor-pointer border-b last:border-b-0"
              onClick={() => handleSelect(item)}
            >
              <div className="font-medium truncate">{item.title}</div>
              <div className="text-xs text-gray-500 capitalize">
                {item.entity_type.replaceAll("_", " ")}
                {item.subtitle && ` · ${item.subtitle}`}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
