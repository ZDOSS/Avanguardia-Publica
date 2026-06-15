import type { Metadata } from "next";
import DirectoryClient from "./DirectoryClient";

export const metadata: Metadata = {
  title: "Government Directory | Avanguardia Publica",
  description:
    "Browse U.S. politicians organized by government branch, chamber, and office — from Congress and the White House to state legislatures and local government.",
};

export default function DirectoryPage() {
  return <DirectoryClient />;
}
