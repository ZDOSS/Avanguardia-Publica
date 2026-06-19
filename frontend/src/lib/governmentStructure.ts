// Comprehensive structural map of the U.S. Government (Federal, State, Local).
//
// This is the *static skeleton* the directory renders as nested links. Every node
// is always shown even when no politician data is attached yet, so the directory is
// a complete, browsable map of government. Real politicians are bucketed onto the
// matching leaf nodes at render time (see classifyToPath in DirectoryClient).
//
// Node `label`s here are the contract the classifier maps onto — keep them in sync.

export interface GovNode {
  label: string;
  icon?: string;
  children?: GovNode[];
}

export const GOV_STRUCTURE: GovNode[] = [
  {
    label: "Federal Government",
    icon: "🏛️",
    children: [
      {
        label: "Legislative Branch (Congress)",
        icon: "⚖️",
        children: [
          {
            label: "Senate (100 Members)",
            children: [
              { label: "Leadership (VP, President Pro Tempore, Majority/Minority Leaders)" },
              {
                label: "Standing Committees",
                children: [
                  { label: "Agriculture, Nutrition, and Forestry" },
                  { label: "Appropriations" },
                  { label: "Armed Services" },
                  { label: "Banking, Housing, and Urban Affairs" },
                  { label: "Budget" },
                  { label: "Commerce, Science, and Transportation" },
                  { label: "Energy and Natural Resources" },
                  { label: "Environment and Public Works" },
                  { label: "Finance" },
                  { label: "Foreign Relations" },
                  { label: "Health, Education, Labor, and Pensions (HELP)" },
                  { label: "Homeland Security and Governmental Affairs" },
                  { label: "Judiciary" },
                  { label: "Rules and Administration" },
                  { label: "Small Business and Entrepreneurship" },
                  { label: "Veterans' Affairs" },
                ],
              },
              {
                label: "Special, Select, and Other Committees",
                children: [
                  { label: "Select Committee on Intelligence" },
                  { label: "Special Committee on Aging" },
                  { label: "Select Committee on Ethics" },
                  { label: "Committee on Indian Affairs" },
                ],
              },
            ],
          },
          {
            label: "House of Representatives (435 Members)",
            children: [
              { label: "Leadership (Speaker of the House, Majority/Minority Leaders, Whips)" },
              {
                label: "Standing Committees",
                children: [
                  { label: "Agriculture" },
                  { label: "Appropriations" },
                  { label: "Armed Services" },
                  { label: "Budget" },
                  { label: "Education and the Workforce" },
                  { label: "Energy and Commerce" },
                  { label: "Ethics" },
                  { label: "Financial Services" },
                  { label: "Foreign Affairs" },
                  { label: "Homeland Security" },
                  { label: "House Administration" },
                  { label: "Judiciary" },
                  { label: "Natural Resources" },
                  { label: "Oversight and Accountability" },
                  { label: "Rules" },
                  { label: "Science, Space, and Technology" },
                  { label: "Small Business" },
                  { label: "Transportation and Infrastructure" },
                  { label: "Veterans' Affairs" },
                  { label: "Ways and Means" },
                ],
              },
              {
                label: "Select Committees",
                children: [
                  { label: "Permanent Select Committee on Intelligence" },
                  { label: "Select Committee on the Strategic Competition Between the U.S. and the CCP" },
                ],
              },
            ],
          },
          {
            label: "Joint Committees",
            children: [
              { label: "Joint Economic Committee" },
              { label: "Joint Committee on the Library" },
              { label: "Joint Committee on Printing" },
              { label: "Joint Committee on Taxation" },
            ],
          },
          {
            label: "Legislative Support Agencies",
            children: [
              { label: "Government Accountability Office (GAO)" },
              { label: "Congressional Budget Office (CBO)" },
              { label: "Library of Congress (LOC)" },
              { label: "Government Publishing Office (GPO)" },
              { label: "Architect of the Capitol" },
            ],
          },
        ],
      },
      {
        label: "Executive Branch",
        icon: "🤝",
        children: [
          { label: "The President" },
          { label: "The Vice President" },
          {
            label: "Executive Office of the President (EOP)",
            children: [
              { label: "White House Office (Chief of Staff, Press Secretary)" },
              { label: "National Security Council (NSC)" },
              { label: "Office of Management and Budget (OMB)" },
              { label: "Council of Economic Advisers (CEA)" },
              { label: "Council on Environmental Quality (CEQ)" },
              { label: "Office of the U.S. Trade Representative" },
              { label: "Office of Science and Technology Policy" },
              { label: "Office of National Drug Control Policy" },
            ],
          },
          {
            label: "The Cabinet (15 Executive Departments)",
            children: [
              { label: "Department of State" },
              { label: "Department of the Treasury" },
              { label: "Department of Defense" },
              {
                label: "Department of Justice (DOJ)",
                children: [{ label: "FBI" }, { label: "DEA" }, { label: "ATF" }, { label: "U.S. Marshals Service" }],
              },
              { label: "Department of the Interior" },
              { label: "Department of Agriculture (USDA)" },
              { label: "Department of Commerce" },
              { label: "Department of Labor" },
              {
                label: "Department of Health and Human Services (HHS)",
                children: [{ label: "CDC" }, { label: "FDA" }, { label: "NIH" }, { label: "CMS" }],
              },
              { label: "Department of Housing and Urban Development (HUD)" },
              {
                label: "Department of Transportation (DOT)",
                children: [{ label: "FAA" }, { label: "NHTSA" }],
              },
              { label: "Department of Energy (DOE)" },
              { label: "Department of Education" },
              { label: "Department of Veterans Affairs (VA)" },
              {
                label: "Department of Homeland Security (DHS)",
                children: [
                  { label: "Customs and Border Protection (CBP)" },
                  { label: "Immigration and Customs Enforcement (ICE)" },
                  { label: "TSA" },
                  { label: "FEMA" },
                  { label: "Coast Guard" },
                  { label: "Secret Service" },
                ],
              },
            ],
          },
          {
            label: "Independent Agencies and Government Corporations",
            children: [
              { label: "Environmental Protection Agency (EPA)" },
              { label: "Central Intelligence Agency (CIA)" },
              { label: "National Aeronautics and Space Administration (NASA)" },
              { label: "United States Postal Service (USPS)" },
              { label: "Federal Reserve System (The Fed)" },
              { label: "Social Security Administration (SSA)" },
              { label: "Federal Communications Commission (FCC)" },
              { label: "Securities and Exchange Commission (SEC)" },
              { label: "Federal Trade Commission (FTC)" },
              { label: "National Science Foundation (NSF)" },
              { label: "United States Agency for International Development (USAID)" },
            ],
          },
        ],
      },
      {
        label: "Judicial Branch",
        icon: "🔨",
        children: [
          {
            label: "Supreme Court of the United States",
            children: [{ label: "Chief Justice" }, { label: "8 Associate Justices" }],
          },
          {
            label: "U.S. Courts of Appeals",
            children: [
              { label: "12 Regional Circuit Courts" },
              { label: "1 Court of Appeals for the Federal Circuit" },
            ],
          },
          {
            label: "U.S. District Courts (Trial Courts)",
            children: [{ label: "94 Federal Judicial Districts" }],
          },
          {
            label: "Article I / Special Courts",
            children: [
              { label: "U.S. Bankruptcy Courts" },
              { label: "U.S. Tax Court" },
              { label: "U.S. Court of International Trade" },
              { label: "U.S. Court of Federal Claims" },
              { label: "U.S. Court of Appeals for Veterans Claims" },
              { label: "U.S. Court of Appeals for the Armed Forces" },
            ],
          },
        ],
      },
    ],
  },
  {
    label: "State Government (General Model for 50 States)",
    icon: "🗺️",
    children: [
      {
        label: "State Legislative Branch",
        icon: "📜",
        children: [
          {
            label: "State Senate (Upper Chamber)",
            children: [
              { label: "Leadership (President of Senate / Lt. Governor)" },
              { label: "State Senate Committees (e.g., Finance, Education, Judiciary)" },
            ],
          },
          {
            label: "State House of Representatives / Assembly / House of Delegates (Lower Chamber)",
            children: [
              { label: "Leadership (Speaker of the House)" },
              { label: "State House Committees (e.g., Ways and Means, Transportation)" },
            ],
          },
          {
            label: "Legislative Support Agencies",
            children: [
              { label: "State Auditor's Office" },
              { label: "Legislative Reference Bureau / Council" },
            ],
          },
        ],
      },
      {
        label: "State Executive Branch",
        icon: "🏷️",
        children: [
          { label: "The Governor (Chief Executive)" },
          { label: "Lieutenant Governor" },
          {
            label: "Elected Executive Officers (Varies by State)",
            children: [
              { label: "Attorney General (Chief Legal Officer)" },
              { label: "Secretary of State (Elections, Business Registry)" },
              { label: "State Treasurer / Comptroller" },
              { label: "Superintendent of Public Instruction / Education" },
            ],
          },
          {
            label: "State Agencies and Departments",
            children: [
              { label: "Department of Transportation (DOT)" },
              { label: "Department of Education (DOE)" },
              { label: "Department of Health / Public Health (DPH)" },
              { label: "Department of Corrections / Prisons" },
              { label: "Department of Environmental Quality / Protection" },
              { label: "State Police / Highway Patrol" },
              { label: "Department of Revenue / Taxation" },
              { label: "Department of Labor and Workforce Development" },
              { label: "Department of Motor Vehicles (DMV)" },
              { label: "Department of Natural Resources (DNR)" },
            ],
          },
        ],
      },
      {
        label: "State Judicial Branch",
        icon: "🔨",
        children: [
          {
            label: "State Supreme Court (Court of Last Resort)",
            children: [{ label: "Chief Justice & Associate Justices" }],
          },
          {
            label: "State Court of Appeals (Intermediate Appellate Courts)",
            children: [{ label: "Appellate Judges" }],
          },
          {
            label: "State Trial Courts (General Jurisdiction)",
            children: [
              { label: "Circuit Courts" },
              { label: "Superior Courts" },
              { label: "District Courts" },
            ],
          },
          {
            label: "Lower Courts (Limited Jurisdiction)",
            children: [
              { label: "Family Court" },
              { label: "Probate Court (Wills/Estates)" },
              { label: "Juvenile Court" },
              { label: "Traffic Court" },
              { label: "Small Claims Court" },
            ],
          },
        ],
      },
    ],
  },
  {
    label: "Local Government",
    icon: "🏙️",
    children: [
      {
        label: "County Government",
        icon: "🌾",
        children: [
          {
            label: "Legislative / Executive Authority",
            children: [
              { label: "Board of County Commissioners / Supervisors" },
              { label: "County Council" },
              { label: "County Executive / Administrator (in some counties)" },
            ],
          },
          {
            label: "Elected County Officials",
            children: [
              { label: "County Sheriff (Law Enforcement & Jails)" },
              { label: "District Attorney / County Prosecutor" },
              { label: "County Clerk (Records, Local Elections)" },
              { label: "County Tax Assessor / Collector" },
              { label: "County Coroner / Medical Examiner" },
            ],
          },
          {
            label: "County Departments & Agencies",
            children: [
              { label: "Public Works (County Roads, Bridges)" },
              { label: "County Health Department" },
              { label: "Department of Social Services / Welfare" },
              { label: "Parks and Recreation" },
              { label: "Emergency Management" },
            ],
          },
          {
            label: "County / Municipal Courts",
            children: [
              { label: "County Courts (Misdemeanors, Civil Claims)" },
              { label: "Justice of the Peace / Magistrate Courts" },
            ],
          },
        ],
      },
      {
        label: "Municipal Government (Cities, Towns, Villages)",
        icon: "🏠",
        children: [
          {
            label: "Legislative Branch",
            children: [
              { label: "City Council / Board of Aldermen / Town Board" },
              { label: "Municipal Committees (e.g., Zoning, Public Safety, Finance)" },
            ],
          },
          {
            label: "Executive Branch",
            children: [
              { label: "Mayor (Chief Executive)" },
              { label: "City Manager / Town Administrator (Appointed Professional)" },
            ],
          },
          {
            label: "City Departments",
            children: [
              { label: "Police Department" },
              { label: "Fire Department & EMS" },
              { label: "Public Works (Water, Trash, Street Maintenance)" },
              { label: "Planning and Zoning Department" },
              { label: "Building Inspection / Code Enforcement" },
              { label: "Parks and Recreation" },
              { label: "Housing Authority" },
            ],
          },
          {
            label: "Municipal Courts",
            children: [
              { label: "City Ordinance Violation Hearings" },
              { label: "Local Traffic Ticket Adjudication" },
            ],
          },
        ],
      },
      {
        label: "Special Districts (Independent Entities)",
        icon: "🏫",
        children: [
          {
            label: "School Districts (Over 13,000 nationwide)",
            children: [
              { label: "Board of Education / School Board (Elected Legislative Body)" },
              { label: "Superintendent of Schools (Appointed Executive)" },
              { label: "District Administration (HR, Curriculum, Transportation)" },
              { label: "Individual Public Schools (Principals, Teachers, Staff)" },
            ],
          },
          {
            label: "Utility & Resource Districts",
            children: [
              { label: "Water and Sewer Districts" },
              { label: "Public Utility Districts (Electricity, Gas)" },
              { label: "Irrigation and Conservation Districts" },
              { label: "Solid Waste Management Districts" },
            ],
          },
          {
            label: "Public Safety & Infrastructure Districts",
            children: [
              { label: "Fire Protection Districts" },
              { label: "Emergency Medical Services (EMS) Districts" },
              { label: "Transit Authorities / Regional Transportation Districts (RTD)" },
              { label: "Airport Authorities" },
              { label: "Port Authorities" },
            ],
          },
          {
            label: "Community Service Districts",
            children: [
              { label: "Library Districts" },
              { label: "Park and Recreation Districts" },
              { label: "Hospital Districts" },
              { label: "Cemetery Districts" },
              { label: "Housing Authorities" },
            ],
          },
        ],
      },
    ],
  },
];

// Path (array of node labels, root → leaf) a politician's office maps onto. Must
// match labels in GOV_STRUCTURE above so the politician attaches to a real node.
export type GovPath = string[];
