export function chamberLabel(chamber: string, countryCode?: string): string {
  switch (chamber) {
    case "senate":
      return "Senator";
    case "house":
      return countryCode === "CA" ? "MP" : "Representative";
    case "state_senate":
      return "State Senator";
    case "state_house":
      return "State Representative";
    case "state_executive":
      return "Statewide Officeholder";
    case "governor":
      return "Governor";
    default:
      return chamber;
  }
}
