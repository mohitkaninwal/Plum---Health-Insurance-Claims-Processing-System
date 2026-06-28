"use client";

import Image from "next/image";
import { startTransition, useEffect, useRef, useState, type ReactNode } from "react";
import {
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  BadgeCheck,
  BarChart3,
  CheckCircle2,
  Clock3,
  FileText,
  Hospital,
  Layers3,
  Loader2,
  Menu,
  Paperclip,
  RefreshCw,
  Sparkles,
  UploadCloud,
  XCircle
} from "lucide-react";

type ViewKey = "submit" | "decision" | "eval";
type ClaimCategory = "CONSULTATION" | "DIAGNOSTIC" | "PHARMACY" | "DENTAL" | "VISION" | "ALTERNATIVE_MEDICINE";
type DocumentType =
  | "PRESCRIPTION"
  | "HOSPITAL_BILL"
  | "LAB_REPORT"
  | "DIAGNOSTIC_REPORT"
  | "PHARMACY_BILL"
  | "DISCHARGE_SUMMARY"
  | "DENTAL_REPORT"
  | "UNKNOWN";

type DecisionType = "APPROVED" | "PARTIAL" | "REJECTED" | "MANUAL_REVIEW";

type ApiDocument = {
  file_id: string;
  file_name?: string | null;
  declared_type?: DocumentType | null;
  actual_type?: DocumentType | null;
  quality?: string;
  patient_name_on_doc?: string | null;
  content?: Record<string, unknown> | null;
};

type ClaimResponse = {
  claim_id: string;
  status: string;
  submitted_at?: string;
  submission?: {
    member_id: string;
    policy_id: string;
    claim_category: ClaimCategory;
    treatment_date: string;
    claimed_amount: number;
    hospital_name?: string | null;
  } | null;
  decision?: {
    decision: DecisionType;
    approved_amount: number;
    confidence_score: number;
    reason: string;
    rejection_reasons: string[];
    line_item_decisions: Array<{
      description: string;
      claimed_amount: number;
      approved_amount: number;
      decision: "APPROVED" | "REJECTED" | "ADJUSTED" | "REVIEW";
      reason: string;
    }>;
  } | null;
  approved_amount?: number | null;
  confidence_score?: number | null;
  reason?: string | null;
  rejection_reasons?: string[];
  line_item_decisions?: Array<{
    description: string;
    claimed_amount: number;
    approved_amount: number;
    decision: "APPROVED" | "REJECTED" | "ADJUSTED" | "REVIEW";
    reason: string;
  }>;
  extracted_document_data?: Array<{
    file_id: string;
    document_type: DocumentType;
    fields: Record<string, unknown>;
    missing_fields: string[];
    confidence: number;
    warnings: string[];
  }>;
  member_action_required?: {
    code: string;
    message: string;
    affected_file_ids: string[];
    required_document_types: DocumentType[];
  } | null;
  trace?: Array<{
    timestamp: string;
    component: string;
    level: "INFO" | "WARNING" | "ERROR";
    message: string;
    input_summary?: Record<string, unknown>;
    output_summary?: Record<string, unknown>;
    checks_performed?: string[];
    evidence_ids?: string[];
    confidence_impact?: number;
    warnings?: string[];
    errors?: string[];
  }>;
  retrieved_policy_evidence?: Array<{
    evidence_id: string;
    source: string;
    source_path?: string | null;
    rule_category: string;
    claim_category?: ClaimCategory | null;
    text: string;
    dense_score?: number | null;
    lexical_score?: number | null;
    rrf_score?: number | null;
  }>;
  component_failures?: Array<{
    component: string;
    message: string;
    recoverable: boolean;
  }>;
};

type PolicyContext = {
  policy_id: string;
  policy_name: string;
  insurer: string;
  company_name: string;
  members: Array<{
    member_id: string;
    name: string;
    relationship: string;
    join_date?: string | null;
    primary_member_id?: string | null;
    dependents: string[];
  }>;
  unresolved_dependent_ids: string[];
};

type MemberYtdSummary = {
  policy_id: string;
  member_id: string;
  as_of_date: string;
  ytd_claims_amount: number;
  claim_count: number;
  claim_ids: string[];
};

type DocumentParseResponse = {
  extracted_documents: Array<{
    file_id: string;
    document_type: DocumentType;
    quality: "GOOD" | "LOW" | "UNREADABLE" | "UNKNOWN";
    fields: Record<string, unknown>;
    missing_fields: string[];
    confidence: number;
    warnings: string[];
  }>;
  trace?: Array<{
    timestamp: string;
    component: string;
    level: "INFO" | "WARNING" | "ERROR";
    message: string;
    input_summary?: Record<string, unknown>;
    output_summary?: Record<string, unknown>;
    checks_performed?: string[];
    evidence_ids?: string[];
    confidence_impact?: number;
    warnings?: string[];
    errors?: string[];
  }>;
  component_failures?: Array<{
    component: string;
    message: string;
    recoverable: boolean;
  }>;
  member_action_required?: {
    code: string;
    message: string;
    affected_file_ids: string[];
    required_document_types: DocumentType[];
  } | null;
  confidence_impact?: number;
};

type EvalRun = {
  eval_run_id: string;
  status: string;
  started_at: string;
  completed_at?: string | null;
  metrics: {
    total_cases: number;
    completed_cases: number;
    decision_accuracy?: number | null;
    early_stop_accuracy?: number | null;
    approved_amount_exact_match_rate?: number | null;
    system_must_accuracy?: number | null;
    rejection_reason_precision?: number | null;
    rejection_reason_recall?: number | null;
    rejection_reason_f1?: number | null;
  };
  cases: Array<{
    case_id: string;
    case_name: string;
    passed?: boolean | null;
    expected: Record<string, unknown>;
    actual?: ClaimResponse | null;
    notes: string[];
  }>;
};

type DocumentDraft = {
  id: string;
  file: File | null;
  declaredType: DocumentType;
  patientName: string;
  quality: "GOOD" | "LOW" | "UNREADABLE" | "UNKNOWN";
  parsedDocumentType?: DocumentType | null;
  parsedFields?: Record<string, unknown>;
  parsedMissingFields?: string[];
  parsedConfidence?: number | null;
  parsedWarnings?: string[];
};

type ClaimDraft = {
  memberId: string;
  policyId: string;
  claimCategory: ClaimCategory;
  treatmentDate: string;
  claimedAmount: string;
  ytdClaimsAmount: string;
  hospitalName: string;
  documents: DocumentDraft[];
};

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

const defaultDraft: ClaimDraft = {
  memberId: "",
  policyId: "",
  claimCategory: "CONSULTATION",
  treatmentDate: "",
  claimedAmount: "",
  ytdClaimsAmount: "",
  hospitalName: "",
  documents: []
};

export default function Home() {
  const [view, setView] = useState<ViewKey>("submit");
  const [navOverHero, setNavOverHero] = useState(true);
  const [draft, setDraft] = useState<ClaimDraft>(defaultDraft);
  const [claimResponse, setClaimResponse] = useState<ClaimResponse | null>(null);
  const [parseResponse, setParseResponse] = useState<DocumentParseResponse | null>(null);
  const [policyContext, setPolicyContext] = useState<PolicyContext | null>(null);
  const [memberYtd, setMemberYtd] = useState<MemberYtdSummary | null>(null);
  const [hasReviewResult, setHasReviewResult] = useState(false);
  const [evalRun, setEvalRun] = useState<EvalRun | null>(null);
  const [expandedCaseId, setExpandedCaseId] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState<string>("Upload documents to start.");
  const [loading, setLoading] = useState<"submit" | "eval" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitValidationError, setSubmitValidationError] = useState<ClaimResponse["member_action_required"] | null>(null);
  const [submitStep, setSubmitStep] = useState<"upload" | "details">("upload");
  const [isDragging, setIsDragging] = useState(false);
  const parseRequestId = useRef(0);
  const ytdRequestId = useRef(0);

  useEffect(() => {
    function syncNavbarTheme() {
      setNavOverHero(window.scrollY < window.innerHeight - 140);
    }

    syncNavbarTheme();
    window.addEventListener("scroll", syncNavbarTheme, { passive: true });
    window.addEventListener("resize", syncNavbarTheme);
    return () => {
      window.removeEventListener("scroll", syncNavbarTheme);
      window.removeEventListener("resize", syncNavbarTheme);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function loadPolicyContext() {
      try {
        const result = await fetch(`${apiBaseUrl}/claims/context`);
        if (!result.ok) {
          throw new Error(`Failed to load policy context with status ${result.status}`);
        }
        const payload = (await result.json()) as PolicyContext;
        if (cancelled) return;
        setPolicyContext(payload);
        setDraft((current) => ({
          ...current,
          policyId: payload.policy_id
        }));
      } catch (contextError) {
        if (cancelled) return;
        setError(contextError instanceof Error ? contextError.message : "Failed to load policy context");
        setStatusMessage("Policy context could not be loaded.");
      }
    }

    void loadPolicyContext();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!draft.memberId || !draft.treatmentDate || !policyContext?.policy_id) {
      setMemberYtd(null);
      setDraft((current) => ({ ...current, ytdClaimsAmount: "" }));
      return;
    }

    const requestId = ytdRequestId.current + 1;
    ytdRequestId.current = requestId;
    setMemberYtd(null);

    let cancelled = false;
    async function loadMemberYtd() {
      try {
        const query = new URLSearchParams();
        if (draft.treatmentDate) {
          query.set("as_of_date", draft.treatmentDate);
        }
        const result = await fetch(
          `${apiBaseUrl}/claims/members/${encodeURIComponent(draft.memberId)}/ytd${query.toString() ? `?${query.toString()}` : ""}`
        );
        if (!result.ok) {
          throw new Error(`Failed to load YTD claims with status ${result.status}`);
        }
        const payload = (await result.json()) as MemberYtdSummary;
        if (cancelled || ytdRequestId.current !== requestId) return;
        setMemberYtd(payload);
        setDraft((current) => ({ ...current, ytdClaimsAmount: String(payload.ytd_claims_amount) }));
      } catch (ytdError) {
        if (cancelled || ytdRequestId.current !== requestId) return;
        setMemberYtd(null);
        setDraft((current) => ({ ...current, ytdClaimsAmount: "0" }));
      }
    }

    void loadMemberYtd();
    return () => {
      cancelled = true;
    };
  }, [draft.memberId, draft.treatmentDate, policyContext?.policy_id]);

  function buildParseFormData(nextDraft: ClaimDraft): FormData {
    const formData = new FormData();
    if (nextDraft.memberId) formData.append("member_id", nextDraft.memberId);
    if (nextDraft.policyId) formData.append("policy_id", nextDraft.policyId);
    if (nextDraft.claimCategory) formData.append("claim_category", nextDraft.claimCategory);
    if (nextDraft.treatmentDate) formData.append("treatment_date", nextDraft.treatmentDate);
    if (nextDraft.claimedAmount) formData.append("claimed_amount", nextDraft.claimedAmount);
    if (nextDraft.ytdClaimsAmount) formData.append("ytd_claims_amount", nextDraft.ytdClaimsAmount);
    if (nextDraft.hospitalName) formData.append("hospital_name", nextDraft.hospitalName);

    const declaredTypes: Record<string, DocumentType> = {};
    const patientNames: Record<string, string> = {};

    nextDraft.documents.forEach((document, index) => {
      if (!document.file) return;
      formData.append("files", document.file);
      declaredTypes[document.file.name || `upload_${index + 1}`] = document.declaredType;
      if (document.patientName) {
        patientNames[document.file.name || `upload_${index + 1}`] = document.patientName;
      }
    });

    if (Object.keys(declaredTypes).length > 0) {
      formData.append("declared_types", JSON.stringify(declaredTypes));
    }
    if (Object.keys(patientNames).length > 0) {
      formData.append("patient_names", JSON.stringify(patientNames));
    }

    return formData;
  }

  function applyParseResult(nextDraft: ClaimDraft, payload: DocumentParseResponse): ClaimDraft {
    const documents = nextDraft.documents.map((document, index) => {
      const parsed = payload.extracted_documents[index];
      if (!parsed) return document;

      const parsedPatientName =
        typeof parsed.fields.patient_name === "string" ? parsed.fields.patient_name : "";
      return {
        ...document,
        declaredType: parsed.document_type === "UNKNOWN" ? document.declaredType : parsed.document_type,
        quality: parsed.quality ?? document.quality,
        patientName: document.patientName || parsedPatientName,
        parsedDocumentType: parsed.document_type,
        parsedFields: parsed.fields,
        parsedMissingFields: parsed.missing_fields,
        parsedConfidence: parsed.confidence,
        parsedWarnings: parsed.warnings
      };
    });

    const firstParsedHospital = documents.find((doc) => {
      const hospitalName = doc.parsedFields?.hospital_name;
      return typeof hospitalName === "string" && hospitalName.trim().length > 0;
    });
    const firstParsedTotal = documents.find((doc) => {
      const total = doc.parsedFields?.total;
      return typeof total === "number" && Number.isFinite(total);
    });
    const firstParsedDate = documents.find((doc) => {
      const invoiceDate = doc.parsedFields?.invoice_date;
      return typeof invoiceDate === "string" && invoiceDate.trim().length > 0;
    });
    const suggestedClaimCategory = inferClaimCategoryFromDocuments(documents) ?? nextDraft.claimCategory;
    const matchedMemberId = findMemberIdByPatientNames(
      documents
        .map((document) => document.patientName)
        .filter((name): name is string => name.trim().length > 0)
    );

    return {
      ...nextDraft,
      documents,
      memberId: nextDraft.memberId || matchedMemberId || "",
      claimCategory: suggestedClaimCategory,
      hospitalName:
        nextDraft.hospitalName ||
        (typeof firstParsedHospital?.parsedFields?.hospital_name === "string"
          ? String(firstParsedHospital.parsedFields.hospital_name)
          : ""),
      claimedAmount:
        typeof firstParsedTotal?.parsedFields?.total === "number"
          ? String(firstParsedTotal.parsedFields.total)
          : nextDraft.claimedAmount,
      treatmentDate:
        typeof firstParsedDate?.parsedFields?.invoice_date === "string"
          ? String(firstParsedDate.parsedFields.invoice_date)
          : nextDraft.treatmentDate
    };
  }

  function findMemberIdByPatientNames(patientNames: string[]): string | null {
    if (!policyContext?.members.length) return null;

    const memberByName = new Map(
      policyContext.members.map((member) => [normalizePersonName(member.name), member.member_id])
    );
    for (const patientName of patientNames) {
      const memberId = memberByName.get(normalizePersonName(patientName));
      if (memberId) return memberId;
    }
    return null;
  }

  function normalizePersonName(value: string): string {
    return value.trim().replace(/\s+/g, " ").toLowerCase();
  }

  function formatMemberLabel(member: PolicyContext["members"][number]): string {
    const relation = member.relationship.replace(/_/g, " ");
    const primarySuffix = member.primary_member_id ? ` · ${member.primary_member_id}` : "";
    return `${member.member_id} · ${member.name} · ${relation}${primarySuffix}`;
  }

  function inferClaimCategoryFromDocuments(documents: DocumentDraft[]): ClaimCategory | null {
    const types = documents
      .map((document) => document.parsedDocumentType ?? document.declaredType)
      .filter((type): type is DocumentType => Boolean(type) && type !== "UNKNOWN");

    if (types.includes("DENTAL_REPORT")) return "DENTAL";
    if (types.includes("PHARMACY_BILL")) return "PHARMACY";
    if (types.includes("LAB_REPORT") || types.includes("DIAGNOSTIC_REPORT")) return "DIAGNOSTIC";
    if (types.includes("HOSPITAL_BILL") || types.includes("PRESCRIPTION") || types.includes("DISCHARGE_SUMMARY")) {
      return "CONSULTATION";
    }
    return null;
  }

  async function parseUploadedDocuments(nextDraft: ClaimDraft) {
    const files = nextDraft.documents.filter((doc) => doc.file);
    if (!files.length) {
      setParseResponse(null);
      return;
    }

    const requestId = parseRequestId.current + 1;
    parseRequestId.current = requestId;
    setStatusMessage(`Parsing ${files.length} uploaded document${files.length > 1 ? "s" : ""}...`);

    try {
      const result = await fetch(`${apiBaseUrl}/claims/parse/upload`, {
        method: "POST",
        body: buildParseFormData(nextDraft)
      });

      if (!result.ok) {
        throw new Error(`Parse request failed with status ${result.status}`);
      }

      const payload = (await result.json()) as DocumentParseResponse;
      if (parseRequestId.current !== requestId) {
        return;
      }

      setParseResponse(payload);
      setDraft((current) => applyParseResult(current, payload));
      setStatusMessage(`Parsed ${payload.extracted_documents.length} document${payload.extracted_documents.length > 1 ? "s" : ""}.`);
    } catch (parseError) {
      if (parseRequestId.current !== requestId) {
        return;
      }
      setParseResponse(null);
      setStatusMessage("Document parsing failed. You can still fill the form manually.");
      setError(parseError instanceof Error ? parseError.message : "Document parsing failed");
    }
  }

  async function handleSubmitClaim() {
    setLoading("submit");
    setError(null);
    setSubmitValidationError(null);
    setStatusMessage("Submitting claim and waiting for adjudication...");

    try {
      const hasFiles = draft.documents.some((doc) => doc.file);
      if (!hasFiles) {
        throw new Error("Upload at least one document before submitting.");
      }

      if (!draft.memberId || !draft.policyId || !draft.treatmentDate || !draft.claimedAmount) {
        throw new Error("Fill member ID, policy ID, treatment date, and claimed amount before submitting.");
      }

      const documents: ApiDocument[] = draft.documents
        .filter((document) => document.file)
        .map((document, index) => {
          const parsedFields = document.parsedFields ?? {};
          const patientName = document.patientName || (typeof parsedFields.patient_name === "string" ? parsedFields.patient_name : "");
          return {
            file_id: `UPL${String(index + 1).padStart(3, "0")}`,
            file_name: document.file?.name ?? null,
            declared_type: document.declaredType,
            actual_type: document.declaredType,
            quality: document.quality,
            patient_name_on_doc: patientName || null,
            content: {
              ...parsedFields,
              parsed_fields: parsedFields,
              parsed_document_type: document.parsedDocumentType ?? null,
              parsed_confidence: document.parsedConfidence ?? null,
              parsed_missing_fields: document.parsedMissingFields ?? [],
              parsed_warnings: document.parsedWarnings ?? []
            }
          };
        });

      const payload = {
        member_id: draft.memberId,
        policy_id: draft.policyId,
        claim_category: draft.claimCategory,
        treatment_date: draft.treatmentDate,
        claimed_amount: Number(draft.claimedAmount),
        ytd_claims_amount: draft.ytdClaimsAmount ? Number(draft.ytdClaimsAmount) : undefined,
        hospital_name: draft.hospitalName || undefined,
        documents
      };

      const result = await fetch(`${apiBaseUrl}/claims/submit`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify(payload)
      });

      if (!result.ok) throw new Error(`Claim submission failed with status ${result.status}`);
      const response = (await result.json()) as ClaimResponse;

      setClaimResponse(response);
      if (response.status === "ACTION_REQUIRED" && response.member_action_required) {
        setSubmitValidationError(response.member_action_required);
        setHasReviewResult(false);
        setView("submit");
        setStatusMessage("Document issue detected. Fix the problem and resubmit.");
      } else {
        setHasReviewResult(true);
        setView("decision");
        setSubmitStep("upload");
        setStatusMessage(`Claim ${response.claim_id} returned ${response.status}.`);
      }
    } catch (submissionError) {
      setError(submissionError instanceof Error ? submissionError.message : "Submission failed");
      setHasReviewResult(false);
      setStatusMessage("Submission failed. Fix the issue and submit again.");
      setView("submit");
    } finally {
      setLoading(null);
    }
  }

  function addFilesToDraft(files: FileList | File[]) {
    const incoming = Array.from(files);
    const newDocs: DocumentDraft[] = incoming.map((file, i) => {
      const stem = file.name.replace(/\.[^.]+$/, "").toLowerCase().replace(/[-\s]/g, "_");
      let guessedType: DocumentType = "UNKNOWN";
      if (stem.includes("prescription") || stem.includes("rx")) guessedType = "PRESCRIPTION";
      else if (stem.includes("pharmacy") || stem.includes("medicine") || stem.includes("drug")) guessedType = "PHARMACY_BILL";
      else if (stem.includes("lab") || stem.includes("pathology")) guessedType = "LAB_REPORT";
      else if (stem.includes("diagnostic") || stem.includes("scan") || stem.includes("mri") || stem.includes("xray")) guessedType = "DIAGNOSTIC_REPORT";
      else if (stem.includes("discharge")) guessedType = "DISCHARGE_SUMMARY";
      else if (stem.includes("dental")) guessedType = "DENTAL_REPORT";
      else if (stem.includes("bill") || stem.includes("invoice") || stem.includes("receipt")) guessedType = "HOSPITAL_BILL";
      return {
        id: `doc-${Date.now()}-${i}`,
        file,
        declaredType: guessedType,
        patientName: "",
        quality: "UNKNOWN",
        parsedDocumentType: null,
        parsedFields: undefined,
        parsedMissingFields: undefined,
        parsedConfidence: null,
        parsedWarnings: undefined
      };
    });
    const nextDraft = { ...draft, documents: [...draft.documents, ...newDocs] };
    setDraft(nextDraft);
    setClaimResponse(null);
    setHasReviewResult(false);
    setParseResponse(null);
    void parseUploadedDocuments(nextDraft);
  }

  function handleDropZoneFiles(event: React.ChangeEvent<HTMLInputElement>) {
    if (event.target.files?.length) addFilesToDraft(event.target.files);
    event.target.value = "";
  }

  function handleDragOver(event: React.DragEvent) {
    event.preventDefault();
    setIsDragging(true);
  }

  function handleDragLeave() {
    setIsDragging(false);
  }

  function handleDrop(event: React.DragEvent) {
    event.preventDefault();
    setIsDragging(false);
    if (event.dataTransfer.files?.length) addFilesToDraft(event.dataTransfer.files);
  }

  async function handleRunEval() {
    setLoading("eval");
    setError(null);
    setStatusMessage("Running eval suite against the backend...");

    try {
      const result = await fetch(`${apiBaseUrl}/eval/run`, { method: "POST" });
      if (!result.ok) throw new Error(`Eval run failed with status ${result.status}`);
      const payload = (await result.json()) as EvalRun;
      setEvalRun(payload);
      setStatusMessage(`Eval run ${payload.eval_run_id} completed with ${payload.metrics.completed_cases}/${payload.metrics.total_cases} cases.`);
      setView("eval");
    } catch (evalError) {
      setError(evalError instanceof Error ? evalError.message : "Eval run failed");
      setEvalRun(null);
      setStatusMessage("Eval run failed. Fix the issue and run again.");
      setView("eval");
    } finally {
      setLoading(null);
    }
  }
  const activeDecision = claimResponse?.decision ?? null;

  function scrollToSection(targetView: ViewKey) {
    window.setTimeout(() => {
      document.getElementById(`${targetView}-section`)?.scrollIntoView({
        behavior: "smooth",
        block: "start"
      });
    }, 0);
  }

  function navigateToView(targetView: ViewKey) {
    if (targetView === "decision" && !hasReviewResult) {
      setStatusMessage("Submit a claim before opening review.");
      setView("submit");
      scrollToSection("submit");
      return;
    }
    setView(targetView);
    scrollToSection(targetView);
  }

  function handleHeroSubmitClaim() {
    navigateToView("submit");
  }

  async function handleHeroRunEval() {
    await handleRunEval();
    scrollToSection("eval");
  }

  return (
    <main className="min-h-screen bg-[var(--bg)] text-[var(--ink)]">
      <div className="flex min-h-screen w-full flex-col pb-12">
        <nav className={`fixed inset-x-0 top-0 z-50 px-4 sm:px-6 lg:px-8 ${navOverHero ? "pt-4" : "pt-2"}`}>
          <div className={`plum-nav ${navOverHero ? "plum-nav--hero" : "plum-nav--solid"}`}>
            <button
              type="button"
              onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}
              className="flex min-w-0 items-center gap-4 text-left"
            >
              <Image
                src="/plum-assets/plum-logo.svg"
                alt="Plum"
                width={126}
                height={39}
                priority
                className="plum-nav__logo h-auto w-[112px] shrink-0 drop-shadow-[0_8px_20px_rgba(0,0,0,0.35)] sm:w-[126px]"
              />
              <span className="plum-nav__meta hidden min-w-0 sm:block">
                <span className="block text-[11px] font-semibold uppercase tracking-[0.22em] text-[#fff1e5]/75">
                  Plum Claims Ops
                </span>
                <span className="mt-1 block text-sm text-[#fff1e5]/80">Explainable health claims workspace</span>
              </span>
            </button>

            <div className="plum-nav__tabs">
              {([
                ["submit", "Submit", UploadCloud],
                ["decision", "Review", Layers3],
                ["eval", "Evaluate", BarChart3]
              ] as const).map(([key, label, Icon]) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => navigateToView(key)}
                  disabled={key === "decision" && !hasReviewResult}
                  className={`plum-nav__tab ${view === key ? "plum-nav__tab--active" : ""} ${
                    key === "decision" && !hasReviewResult ? "cursor-not-allowed opacity-45" : ""
                  }`}
                >
                  <Icon className="h-4 w-4" />
                  {label}
                </button>
              ))}
            </div>
          </div>
        </nav>

        <header className="relative min-h-screen w-full overflow-hidden bg-[#1d0716] text-white shadow-[0_28px_90px_rgba(29,7,22,0.18)]">
          <Image
            src="/plum-assets/homepage.webp"
            alt="Plum wallpaper background"
            fill
            priority
            className="object-cover"
            sizes="100vw"
          />
          <div className="absolute inset-0 bg-[linear-gradient(180deg,rgba(29,7,22,0.58)_0%,rgba(29,7,22,0.24)_46%,rgba(29,7,22,0.86)_100%)]" />
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_42%,rgba(255,177,136,0.18),transparent_30%)]" />

          <div className="relative mx-auto flex min-h-screen w-full max-w-[1480px] flex-col px-5 py-24 sm:px-7 lg:px-10">
            <div className="mx-auto flex w-full max-w-4xl flex-1 flex-col items-center justify-center text-center">
              <h1 className="max-w-4xl text-5xl font-semibold leading-[0.98] tracking-normal text-[#fffaf2] sm:text-6xl lg:text-7xl">
                Claims review with Plum clarity
              </h1>
              <p className="mt-6 max-w-2xl text-base leading-7 text-[#fff1e5]/88 sm:text-lg">
                Submit claims, inspect policy-backed decisions, and run evaluation checks from a calmer operations desk.
              </p>
              <div className="mt-8 flex flex-wrap justify-center gap-3">
                <button
                  type="button"
                  onClick={handleHeroSubmitClaim}
                  className="inline-flex items-center justify-center gap-2 rounded-full bg-[#ff4658] px-5 py-3 text-sm font-semibold text-white shadow-[0_16px_36px_rgba(255,70,88,0.28)] transition hover:bg-[#ff5b69]"
                >
                  <ArrowRight className="h-4 w-4" />
                  Submit claim
                </button>
                <button
                  type="button"
                  onClick={() => startTransition(() => handleHeroRunEval())}
                  className="inline-flex items-center justify-center gap-2 rounded-full border border-white/35 bg-white/10 px-5 py-3 text-sm font-semibold text-white backdrop-blur-md transition hover:bg-white/18"
                >
                  {loading === "eval" ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                  Run eval
                </button>
              </div>
            </div>

          </div>
        </header>

        <div className="mx-auto flex w-full max-w-[1480px] flex-col gap-8 px-4 pt-8 sm:px-6 lg:px-8">
        {error ? (
          <div className="flex items-start gap-3 rounded-[18px] border border-[#f1c4c0] bg-[#fff1f1] p-4 text-sm text-[#a83d35]">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
        ) : null}

        {view !== "eval" ? (
        <section
          id={view === "submit" ? "submit-section" : "decision-section"}
          className={`scroll-mt-32 ${view === "decision" ? "" : "flex justify-center"}`}
        >
          <div className={view === "decision" ? "hidden" : "w-full max-w-2xl space-y-5"}>
            <Panel title="New claim" icon={<UploadCloud className="h-4 w-4" />}>
              {/* Step indicator */}
              <div className="mb-6 flex items-center gap-0">
                <div className="flex items-center gap-2.5">
                  <div className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-bold ${submitStep === "upload" ? "bg-[var(--plum)] text-white" : "bg-[#e7f4ee] text-[#1f8f5c]"}`}>
                    {submitStep === "details" ? <CheckCircle2 className="h-4 w-4" /> : "1"}
                  </div>
                  <span className={`text-sm font-semibold ${submitStep === "upload" ? "text-[var(--ink)]" : "text-[#1f8f5c]"}`}>
                    Upload documents
                  </span>
                </div>
                <div className={`mx-3 h-px flex-1 transition-colors duration-300 ${submitStep === "details" ? "bg-[var(--plum)]/40" : "bg-[color:var(--line)]"}`} />
                <div className="flex items-center gap-2.5">
                  <div className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-bold ${submitStep === "details" ? "bg-[var(--plum)] text-white" : "bg-[color:var(--line)] text-[var(--muted)]"}`}>2</div>
                  <span className={`text-sm font-semibold ${submitStep === "details" ? "text-[var(--ink)]" : "text-[var(--muted)]"}`}>
                    Claim details
                  </span>
                </div>
              </div>

              {/* ── STEP 1: Upload ── */}
              {submitStep === "upload" && (
                <div className="space-y-4">
                  {/* Drop zone */}
                  <div
                    onDragOver={handleDragOver}
                    onDragLeave={handleDragLeave}
                    onDrop={handleDrop}
                    className={`relative flex flex-col items-center justify-center rounded-[20px] border-2 border-dashed px-8 py-14 text-center transition-colors duration-150 ${isDragging ? "border-[var(--plum)] bg-[#fdf4f9]" : "border-[color:var(--line)] bg-[#fffaf2] hover:border-[var(--plum)]/50"}`}
                  >
                    <input
                      type="file"
                      multiple
                      accept="image/*,.pdf"
                      className="absolute inset-0 cursor-pointer opacity-0"
                      onChange={handleDropZoneFiles}
                    />
                    <div className={`flex h-14 w-14 items-center justify-center rounded-full transition-colors ${isDragging ? "bg-[var(--plum)] text-white" : "bg-[var(--plum)]/10 text-[var(--plum)]"}`}>
                      <UploadCloud className="h-6 w-6" />
                    </div>
                    <p className="mt-4 text-base font-semibold text-[var(--ink)]">
                      {isDragging ? "Drop to upload" : "Drop documents here"}
                    </p>
                    <p className="mt-1 text-sm text-[var(--muted)]">or click anywhere to browse · bills, prescriptions, lab reports, PDFs</p>
                    <p className="mt-3 text-xs text-[var(--muted)]">
                      Documents are parsed as soon as they are uploaded
                    </p>
                  </div>

                  {/* Uploaded files */}
                  {draft.documents.length > 0 && (
                    <div className="space-y-2">
                      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[var(--muted)]">
                        {draft.documents.length} document{draft.documents.length > 1 ? "s" : ""} ready
                      </p>
                      {draft.documents.map((document, index) => (
                        <div key={document.id} className="grid items-start gap-3 rounded-[16px] border border-[color:var(--line)] bg-white p-3.5 sm:grid-cols-[auto_1fr_0.9fr_0.9fr_auto]">
                          {/* File icon + name */}
                          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[10px] bg-[var(--plum)]/8 text-[var(--plum)]">
                            <FileText className="h-5 w-5" />
                          </div>
                          <div className="min-w-0">
                            <p className="truncate text-sm font-semibold text-[var(--ink)]">
                              {document.file ? document.file.name : `Fixture doc ${index + 1}`}
                            </p>
                            <p className="text-xs text-[var(--muted)]">
                              {document.file ? `${(document.file.size / 1024).toFixed(0)} KB` : "No file"}
                            </p>
                            <div className="mt-2 flex flex-wrap gap-2">
                              <span className="rounded-full bg-[var(--plum)]/8 px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--plum)]">
                                Parsed {document.parsedDocumentType ?? document.declaredType}
                              </span>
                              {typeof document.parsedConfidence === "number" ? (
                                <span className="rounded-full bg-[#eef5ff] px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-[#3657a8]">
                                  {Math.round(document.parsedConfidence * 100)}% confidence
                                </span>
                              ) : null}
                            </div>
                            {(document.parsedFields?.patient_name ||
                              document.parsedFields?.hospital_name ||
                              document.parsedFields?.diagnosis ||
                              typeof document.parsedFields?.total !== "undefined") ? (
                              <div className="mt-3 flex flex-wrap gap-2">
                                {document.parsedFields?.patient_name ? (
                                  <DetailChip label="patient" value={String(document.parsedFields.patient_name)} />
                                ) : null}
                                {document.parsedFields?.hospital_name ? (
                                  <DetailChip label="hospital" value={String(document.parsedFields.hospital_name)} />
                                ) : null}
                                {document.parsedFields?.diagnosis ? (
                                  <DetailChip label="diagnosis" value={String(document.parsedFields.diagnosis)} />
                                ) : null}
                                {typeof document.parsedFields?.total !== "undefined" ? (
                                  <DetailChip label="total" value={String(document.parsedFields.total)} />
                                ) : null}
                              </div>
                            ) : null}
                          </div>
                          {/* Type */}
                          <div className="flex flex-col gap-1">
                            <span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[var(--muted)]">Type</span>
                            <select
                              value={document.declaredType}
                              onChange={(event) => setDraft((current) => ({
                                ...current,
                                documents: current.documents.map((item) =>
                                  item.id === document.id ? { ...item, declaredType: event.target.value as DocumentType } : item
                                )
                              }))}
                              className="field py-1.5 text-xs"
                            >
                              {["PRESCRIPTION","HOSPITAL_BILL","LAB_REPORT","DIAGNOSTIC_REPORT","PHARMACY_BILL","DISCHARGE_SUMMARY","DENTAL_REPORT","UNKNOWN"].map((opt) => (
                                <option key={opt} value={opt}>{opt.replace(/_/g, " ")}</option>
                              ))}
                            </select>
                          </div>
                          {/* Quality */}
                          <div className="flex flex-col gap-1">
                            <span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[var(--muted)]">Quality</span>
                            <select
                              value={document.quality}
                              onChange={(event) => setDraft((current) => ({
                                ...current,
                                documents: current.documents.map((item) =>
                                  item.id === document.id ? { ...item, quality: event.target.value as DocumentDraft["quality"] } : item
                                )
                              }))}
                              className="field py-1.5 text-xs"
                            >
                              {["GOOD","LOW","UNREADABLE","UNKNOWN"].map((opt) => (
                                <option key={opt} value={opt}>{opt}</option>
                              ))}
                            </select>
                          </div>
                          {/* Remove */}
                          <button
                            type="button"
                            onClick={() => {
                              const nextDocuments = draft.documents.filter((item) => item.id !== document.id);
                              const nextDraft = { ...draft, documents: nextDocuments };
                              setDraft(nextDraft);
                              setParseResponse(null);
                              if (nextDocuments.some((doc) => doc.file)) {
                                void parseUploadedDocuments(nextDraft);
                              } else {
                                parseRequestId.current += 1;
                              }
                            }}
                            className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-[color:var(--line)] text-[var(--muted)] transition hover:border-[#dfb2a0] hover:text-[var(--ink)]"
                          >
                            <XCircle className="h-4 w-4" />
                          </button>
                        </div>
                      ))}
                    </div>
                  )}

                  <div className="flex items-center justify-between gap-3">
                    <button
                      type="button"
                      disabled={draft.documents.length === 0 || !draft.documents.some((doc) => doc.file)}
                      onClick={() => setSubmitStep("details")}
                      className="inline-flex items-center gap-2 rounded-full bg-[var(--plum)] px-5 py-2.5 text-sm font-semibold text-white transition hover:opacity-95 disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      Continue to details
                      <ArrowRight className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              )}

              {/* ── STEP 2: Details ── */}
              {submitStep === "details" && (
                <div className="space-y-5">
                  {/* Back */}
                  <button
                    type="button"
                    onClick={() => setSubmitStep("upload")}
                    className="inline-flex items-center gap-1.5 text-sm font-medium text-[var(--muted)] transition hover:text-[var(--plum)]"
                  >
                    <ArrowLeft className="h-4 w-4" />
                    Back to documents
                  </button>

                  {/* Extraction notice */}
                  {draft.documents.some((d) => d.file) && (
                    <div className="flex items-start gap-3 rounded-[14px] border border-[#c2e8d4] bg-[#edf8f2] p-3.5">
                      <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-[#1f8f5c]" />
                      <div>
                        <p className="text-sm font-semibold text-[#166b44]">
                          {draft.documents.filter((d) => d.file).length} document{draft.documents.filter((d) => d.file).length > 1 ? "s" : ""} uploaded — parsing runs on upload
                        </p>
                        <p className="mt-0.5 text-xs text-[#1f8f5c]">
                          Extracted fields are filled in as soon as the upload completes.
                        </p>
                      </div>
                    </div>
                  )}

                  {draft.documents.some((d) => d.file) ? (
                    <div className="rounded-[14px] border border-[color:var(--line)] bg-white p-3.5">
                      <div className="flex items-center justify-between gap-3">
                        <p className="text-sm font-semibold text-[var(--ink)]">Parse status</p>
                        <span className="text-xs font-semibold uppercase tracking-[0.16em] text-[var(--muted)]">
                          {parseResponse ? "Parsed" : "Waiting"}
                        </span>
                      </div>
                      <p className="mt-2 text-sm leading-6 text-[var(--muted)]">
                        {parseResponse
                          ? `Extracted ${parseResponse.extracted_documents.length} document${parseResponse.extracted_documents.length > 1 ? "s" : ""} from the latest upload.`
                          : "The latest upload will be parsed automatically and the extracted values will populate the fields below."}
                      </p>
                      {parseResponse?.component_failures?.length ? (
                        <p className="mt-2 text-xs text-[#9c3b34]">
                          {parseResponse.component_failures.map((item) => item.message).join(" · ")}
                        </p>
                      ) : null}
                    </div>
                  ) : null}

                  {/* Form */}
                  <div className="grid gap-4 md:grid-cols-2">
                    <Field label="Policy ID">
                      <input value={policyContext?.policy_id ?? draft.policyId} readOnly className="field bg-[#f7f1ea] text-[var(--muted)]" />
                    </Field>
                    <Field label="Member">
                      <select
                        value={draft.memberId}
                        onChange={(e) => setDraft((c) => ({ ...c, memberId: e.target.value }))}
                        className="field"
                        disabled={!policyContext?.members.length}
                      >
                        {policyContext?.members.length ? (
                          <>
                            <option value="">Select member</option>
                            {policyContext.members.map((member) => (
                              <option key={member.member_id} value={member.member_id}>
                                {formatMemberLabel(member)}
                              </option>
                            ))}
                          </>
                        ) : (
                          <option value="">Loading members...</option>
                        )}
                      </select>
                      {policyContext?.unresolved_dependent_ids?.length ? (
                        <p className="mt-2 text-xs text-[#9f5f17]">
                          Policy references uncovered dependent IDs: {policyContext.unresolved_dependent_ids.join(", ")}
                        </p>
                      ) : null}
                    </Field>
                    <Field label="Claim category">
                      <select value={draft.claimCategory} onChange={(e) => setDraft((c) => ({ ...c, claimCategory: e.target.value as ClaimCategory }))} className="field">
                        {["CONSULTATION","DIAGNOSTIC","PHARMACY","DENTAL","VISION","ALTERNATIVE_MEDICINE"].map((opt) => (
                          <option key={opt} value={opt}>{opt.replace(/_/g, " ")}</option>
                        ))}
                      </select>
                    </Field>
                    <Field label="Treatment date">
                      <input type="date" value={draft.treatmentDate} onChange={(e) => setDraft((c) => ({ ...c, treatmentDate: e.target.value }))} className="field" />
                    </Field>
                    <Field label="Claimed amount (INR)">
                      <input type="number" min="1" value={draft.claimedAmount} onChange={(e) => setDraft((c) => ({ ...c, claimedAmount: e.target.value }))} className="field" />
                    </Field>
                    <Field label="Year-to-date amount">
                      <input
                        type="number"
                        min="0"
                        value={draft.ytdClaimsAmount}
                        readOnly
                        className="field bg-[#f7f1ea] text-[var(--muted)]"
                        placeholder={
                          draft.memberId && draft.treatmentDate
                            ? memberYtd
                              ? "Loaded from claims history"
                              : "Loading..."
                            : "Select member and treatment date"
                        }
                      />
                    </Field>
                    <Field label="Hospital name">
                      <input value={draft.hospitalName} onChange={(e) => setDraft((c) => ({ ...c, hospitalName: e.target.value }))} className="field" placeholder="Optional" />
                    </Field>
                  </div>

                  {/* Per-document patient name */}
                  <div className="space-y-2">
                    <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[var(--muted)]">Patient name on each document</p>
                    {draft.documents.map((document, index) => (
                      <div key={document.id} className="flex items-center gap-3 rounded-[14px] border border-[color:var(--line)] bg-[#fffaf2] p-3">
                        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[var(--plum)]/10 text-[var(--plum)]">
                          <FileText className="h-4 w-4" />
                        </div>
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-xs font-medium text-[var(--ink)]">
                            {document.file ? document.file.name : "Uploaded document"}
                          </p>
                        </div>
                        <input
                          value={document.patientName}
                          onChange={(e) => setDraft((current) => ({
                            ...current,
                            documents: current.documents.map((item) =>
                              item.id === document.id ? { ...item, patientName: e.target.value } : item
                            )
                          }))}
                          className="field w-48 py-1.5 text-sm"
                          placeholder={`Patient name (doc ${index + 1})`}
                        />
                      </div>
                    ))}
                  </div>

                  {/* Validation error from previous submission */}
                  {submitValidationError && (() => {
                    const code = submitValidationError.code;
                    const docTypes = submitValidationError.required_document_types ?? [];

                    // Specific label + colours per error code
                    const DOC_LABELS: Record<string, string> = {
                      HOSPITAL_BILL: "Hospital Bill",
                      PRESCRIPTION: "Doctor's Prescription",
                      LAB_REPORT: "Lab / Diagnostic Report",
                      PHARMACY_BILL: "Pharmacy Bill",
                    };
                    const specificDoc = docTypes.length === 1 ? (DOC_LABELS[docTypes[0]] ?? docTypes[0].replace(/_/g, " ")) : null;

                    type BannerStyle = { border: string; bg: string; badge: string; badgeText: string; icon: string; text: string; sub: string };
                    const STYLES: Record<string, BannerStyle> = {
                      MISSING_REQUIRED_DOCUMENT: { border: "border-[#f5c9a0]", bg: "bg-[#fff7ed]", badge: "bg-[#fed7aa] text-[#92400e]", badgeText: specificDoc ? `Missing: ${specificDoc}` : "Missing Document", icon: "text-[#f97316]", text: "text-[#92400e]", sub: "text-[#78350f]" },
                      UNREADABLE_DOCUMENT:        { border: "border-[#fde68a]", bg: "bg-[#fffbeb]", badge: "bg-[#fef08a] text-[#713f12]", badgeText: "Unreadable Document",  icon: "text-[#d97706]", text: "text-[#713f12]", sub: "text-[#92400e]" },
                      WRONG_DOCUMENT_TYPE:        { border: "border-[#fde68a]", bg: "bg-[#fffbeb]", badge: "bg-[#fef08a] text-[#713f12]", badgeText: "Wrong Document Type",   icon: "text-[#d97706]", text: "text-[#713f12]", sub: "text-[#92400e]" },
                      PATIENT_MISMATCH:           { border: "border-[#e9d5ff]", bg: "bg-[#faf5ff]", badge: "bg-[#e9d5ff] text-[#6b21a8]", badgeText: "Patient Name Mismatch", icon: "text-[#9333ea]", text: "text-[#6b21a8]", sub: "text-[#7c3aed]" },
                    };
                    const s: BannerStyle = STYLES[code] ?? STYLES["MISSING_REQUIRED_DOCUMENT"];

                    // Message structure: headline \n\n context \n\n qualifies \n\n not-qualifies \n\n action
                    const paras = submitValidationError.message.split(/\n\n+/).map((p) => p.trim()).filter(Boolean);
                    // Context = second paragraph ("Your X claim (Claim ID: ...) requires...")
                    const context = paras[1] ?? "";
                    // Action = last paragraph ("Submit your claim again..." / "Upload a government ID...")
                    const action = paras.length > 2 ? paras[paras.length - 1] : "";

                    return (
                      <div className={`rounded-[14px] border ${s.border} ${s.bg} p-4`}>
                        <div className="flex items-start justify-between gap-3">
                          <div className="flex items-start gap-2.5">
                            <AlertCircle className={`mt-0.5 h-4 w-4 shrink-0 ${s.icon}`} />
                            <div className="space-y-1">
                              <span className={`inline-block rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.14em] ${s.badge}`}>
                                {s.badgeText}
                              </span>
                              {context && (
                                <p className={`text-xs leading-5 ${s.sub}`}>{context}</p>
                              )}
                            </div>
                          </div>
                          <button
                            type="button"
                            onClick={() => setSubmitValidationError(null)}
                            className={`shrink-0 opacity-50 hover:opacity-100 ${s.text}`}
                          >
                            <XCircle className="h-4 w-4" />
                          </button>
                        </div>
                        {docTypes.length > 1 && (
                          <div className="mt-2.5 flex flex-wrap gap-1.5">
                            {docTypes.map((dt) => (
                              <span key={dt} className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] ${s.badge}`}>
                                {DOC_LABELS[dt] ?? dt.replace(/_/g, " ")}
                              </span>
                            ))}
                          </div>
                        )}
                        {action && (
                          <p className={`mt-2.5 text-xs font-medium ${s.text}`}>{action}</p>
                        )}
                      </div>
                    );
                  })()}

                  {/* Submit row */}
                  <div className="flex flex-wrap items-center justify-between gap-3 rounded-[18px] border border-[color:var(--line)] bg-[#fffaf2] p-4">
                    <p className="text-sm text-[var(--muted)]">{statusMessage}</p>
                    <button
                      type="button"
                      onClick={() => startTransition(() => handleSubmitClaim())}
                      disabled={
                        loading === "submit" ||
                        !draft.documents.some((doc) => doc.file) ||
                        !draft.memberId ||
                        !draft.policyId ||
                        !draft.treatmentDate ||
                        !draft.claimedAmount ||
                        !memberYtd
                      }
                      className="inline-flex items-center justify-center gap-2 rounded-full bg-[var(--plum)] px-5 py-3 text-sm font-semibold text-white transition hover:opacity-95 disabled:cursor-not-allowed disabled:opacity-70"
                    >
                      {loading === "submit" ? <Loader2 className="h-4 w-4 animate-spin" /> : <UploadCloud className="h-4 w-4" />}
                      Submit for review
                    </button>
                  </div>
                </div>
              )}
            </Panel>
          </div>

          <div className={view === "decision" ? "space-y-6" : "hidden"}>
            {claimResponse ? (
              <>
                {/* Claim header banner */}
                <div className="overflow-hidden rounded-[22px] bg-[linear-gradient(135deg,#1d0716_0%,#3a1128_60%,#251020_100%)] p-6 text-white shadow-[0_8px_32px_rgba(29,7,22,0.22)]">
                  <div className="flex flex-wrap items-start justify-between gap-4">
                    <div>
                      <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-[#fff1e5]/55">Claim ID</p>
                      <p className="mt-1.5 font-mono text-xl font-semibold tracking-wide text-white">{claimResponse.claim_id}</p>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      {typeof (claimResponse.confidence_score ?? claimResponse.decision?.confidence_score) === "number" && (
                        <span className="rounded-full border border-white/15 bg-white/10 px-3.5 py-1.5 text-xs font-semibold text-[#fff1e5]/90">
                          Confidence {Math.round(((claimResponse.confidence_score ?? claimResponse.decision?.confidence_score) as number) * 100)}%
                        </span>
                      )}
                      <span className={`rounded-full px-3.5 py-1.5 text-xs font-semibold uppercase tracking-[0.14em] ${
                        claimResponse.status === "COMPLETED" ? "bg-[#d1fae5] text-[#065f46]"
                        : claimResponse.status === "ACTION_REQUIRED" ? "bg-[#fef3c7] text-[#92400e]"
                        : claimResponse.status === "FAILED" ? "bg-[#fee2e2] text-[#991b1b]"
                        : "bg-white/15 text-[#fff1e5]/80"
                      }`}>
                        {claimResponse.status.replace(/_/g, " ")}
                      </span>
                    </div>
                  </div>
                  {claimResponse.submission && (
                    <div className="mt-5 grid grid-cols-2 gap-x-8 gap-y-3 border-t border-white/10 pt-5 sm:grid-cols-4 lg:grid-cols-6">
                      <div>
                        <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[#fff1e5]/50">Member</p>
                        <p className="mt-1 text-sm font-medium text-[#fff1e5]/90">{claimResponse.submission.member_id}</p>
                      </div>
                      <div>
                        <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[#fff1e5]/50">Category</p>
                        <p className="mt-1 text-sm font-medium text-[#fff1e5]/90">{claimResponse.submission.claim_category.replace(/_/g, " ")}</p>
                      </div>
                      <div>
                        <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[#fff1e5]/50">Treatment date</p>
                        <p className="mt-1 text-sm font-medium text-[#fff1e5]/90">{claimResponse.submission.treatment_date}</p>
                      </div>
                      <div>
                        <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[#fff1e5]/50">Claimed amount</p>
                        <p className="mt-1 text-sm font-medium text-[#fff1e5]/90">INR {claimResponse.submission.claimed_amount.toLocaleString("en-IN")}</p>
                      </div>
                      {typeof (claimResponse.approved_amount ?? claimResponse.decision?.approved_amount) === "number" && (
                        <div>
                          <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[#fff1e5]/50">Approved amount</p>
                          <p className="mt-1 text-sm font-semibold text-[#86efac]">
                            INR {((claimResponse.approved_amount ?? claimResponse.decision?.approved_amount) as number).toLocaleString("en-IN")}
                          </p>
                        </div>
                      )}
                      {claimResponse.submission.hospital_name && (
                        <div className="col-span-2">
                          <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[#fff1e5]/50">Hospital</p>
                          <p className="mt-1 text-sm font-medium text-[#fff1e5]/90">{claimResponse.submission.hospital_name}</p>
                        </div>
                      )}
                      {claimResponse.submitted_at && (
                        <div className="col-span-2">
                          <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[#fff1e5]/50">Submitted at</p>
                          <p className="mt-1 text-sm font-medium text-[#fff1e5]/90">{new Date(claimResponse.submitted_at).toLocaleString("en-IN")}</p>
                        </div>
                      )}
                    </div>
                  )}
                </div>

                {/* Decision + Line-items (left) | Document validation (right) */}
                <div className={`grid gap-6 ${(claimResponse.extracted_document_data?.length ?? 0) > 0 ? "xl:grid-cols-[1.1fr_0.9fr]" : ""}`}>
                  {/* Left column: Decision review + Line-item adjudication */}
                  <div className="space-y-6">
                  <Panel title="Decision review" icon={<BadgeCheck className="h-4 w-4" />}>
                    {activeDecision ? (
                      <div className="grid gap-5 md:grid-cols-[0.82fr_1.18fr]">
                        {/* Left: dark decision card */}
                        <div className="flex flex-col justify-between rounded-[20px] bg-[linear-gradient(160deg,#1d0716,#351325)] p-5 text-white">
                          <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-[#fff1e5]/55">Final decision</p>
                          <div className="mt-4 space-y-1">
                            <DecisionBadge decision={activeDecision.decision} />
                            <div className="pt-2 text-3xl font-semibold tracking-[-0.03em]">
                              INR {activeDecision.approved_amount.toLocaleString("en-IN")}
                            </div>
                            <p className="text-xs text-[#fff1e5]/60">Approved amount</p>
                          </div>
                          <div className="mt-5 rounded-[16px] border border-white/10 bg-white/5 p-4">
                            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[#fff1e5]/55">Confidence</p>
                            <div className="mt-3 flex items-end gap-3">
                              <div className="text-3xl font-semibold">{Math.round((activeDecision.confidence_score ?? 0) * 100)}%</div>
                              <div className="mb-1 flex-1">
                                <div className="h-2 overflow-hidden rounded-full bg-white/10">
                                  <div className="h-full rounded-full bg-[#ffb591]" style={{ width: `${Math.round((activeDecision.confidence_score ?? 0) * 100)}%` }} />
                                </div>
                              </div>
                            </div>
                          </div>
                        </div>
                        {/* Right: summary rows — always shown */}
                        <div className="space-y-3">
                          <SummaryRow label="Reason" value={activeDecision.reason} />
                          <SummaryRow
                            label="Member action required"
                            value={claimResponse.member_action_required?.message ?? "None"}
                          />
                          <SummaryRow
                            label="Rejection reasons"
                            value={claimResponse.rejection_reasons?.length ? claimResponse.rejection_reasons.join(", ") : "None"}
                          />
                          <SummaryRow
                            label="Warnings"
                            value={claimResponse.component_failures?.length ? claimResponse.component_failures.map((f) => f.message).join(" · ") : "No component failures"}
                          />
                        </div>
                      </div>
                    ) : claimResponse.member_action_required ? (
                      <div className="space-y-5">
                        <div className="rounded-[18px] border border-[#f5c9a0] bg-[#fff7ed] p-5">
                          <div className="flex items-center gap-3">
                            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[#f97316] text-white">
                              <AlertCircle className="h-4 w-4" />
                            </div>
                            <div>
                              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#92400e]">Action required</p>
                              <p className="mt-0.5 text-xs font-medium text-[#b45309]">{claimResponse.member_action_required.code.replace(/_/g, " ")}</p>
                            </div>
                          </div>
                          {claimResponse.member_action_required.required_document_types?.length ? (
                            <div className="mt-3 flex flex-wrap gap-2">
                              {claimResponse.member_action_required.required_document_types.map((dt) => (
                                <span key={dt} className="rounded-full bg-[#fed7aa] px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-[#92400e]">{dt.replace(/_/g, " ")}</span>
                              ))}
                            </div>
                          ) : null}
                        </div>
                        <SummaryRow label="What to do" value={claimResponse.member_action_required.message} />
                        {typeof claimResponse.confidence_score === "number" && (
                          <div className="flex items-center gap-4 rounded-[14px] border border-[color:var(--line)] bg-[#fffaf2] px-4 py-3">
                            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[var(--muted)]">Confidence</p>
                            <div className="flex flex-1 items-center gap-3">
                              <div className="h-2 flex-1 overflow-hidden rounded-full bg-[#f3ede8]">
                                <div className="h-full rounded-full bg-[var(--plum)]" style={{ width: `${Math.round(claimResponse.confidence_score * 100)}%` }} />
                              </div>
                              <span className="text-sm font-semibold text-[var(--ink)]">{Math.round(claimResponse.confidence_score * 100)}%</span>
                            </div>
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="flex items-start gap-4 rounded-[18px] border border-[color:var(--line)] bg-[#f7f1ea] p-5">
                        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[var(--muted)]/20 text-[var(--muted)]">
                          <Clock3 className="h-5 w-5" />
                        </div>
                        <div>
                          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[var(--muted)]">Pending</p>
                          <p className="mt-1 text-sm leading-6 text-[var(--muted)]">{claimResponse.reason ?? "No decision produced yet."}</p>
                        </div>
                      </div>
                    )}
                  </Panel>

                  {activeDecision && activeDecision.line_item_decisions.length > 0 && (
                  <Panel title="Line-item adjudication" icon={<Layers3 className="h-4 w-4" />}>
                  <div className="space-y-3">
                    {activeDecision.line_item_decisions.map((item) => (
                      <div key={`${item.description}-${item.claimed_amount}`} className="grid items-center gap-3 rounded-[18px] border border-[color:var(--line)] bg-[#fffaf2] p-4 md:grid-cols-[1fr_auto_auto_auto]">
                        <div>
                          <p className="font-medium text-[var(--ink)]">{item.description}</p>
                          <p className="mt-0.5 text-sm text-[var(--muted)]">{item.reason}</p>
                        </div>
                        <div className="text-right">
                          <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--muted)]">Claimed</p>
                          <p className="mt-0.5 text-sm font-semibold text-[var(--ink)]">INR {item.claimed_amount.toLocaleString("en-IN")}</p>
                        </div>
                        <div className="text-right">
                          <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--muted)]">Approved</p>
                          <p className="mt-0.5 text-sm font-semibold text-[var(--ink)]">INR {item.approved_amount.toLocaleString("en-IN")}</p>
                        </div>
                        <div className="flex justify-end">
                          <LineBadge decision={item.decision} />
                        </div>
                      </div>
                    ))}
                  </div>
                  </Panel>
                  )}

                  </div>{/* end left column */}

                  {(claimResponse.extracted_document_data?.length ?? 0) > 0 && (
                  <Panel title="Document validation" icon={<FileText className="h-4 w-4" />}>
                    <div className="max-h-[600px] space-y-3 overflow-y-auto pr-0.5">
                      {claimResponse.extracted_document_data?.map((doc) => (
                        <div key={doc.file_id} className="rounded-[18px] border border-[color:var(--line)] bg-[#fffaf2] p-4">
                          <div className="flex flex-wrap items-start justify-between gap-2">
                            <div className="min-w-0">
                              <p className="truncate text-sm font-semibold text-[var(--ink)]">
                                {doc.file_id}
                              </p>
                              <p className="text-xs text-[var(--muted)]">{doc.document_type.replace(/_/g, " ")} · {Math.round(doc.confidence * 100)}% confidence</p>
                            </div>
                            <span className={`shrink-0 rounded-full px-2.5 py-1 text-[10px] font-semibold ${doc.missing_fields.length ? "bg-[#fff1db] text-[#9f5f17]" : "bg-[#e7f4ee] text-[#1f8f5c]"}`}>
                              {doc.missing_fields.length ? `${doc.missing_fields.length} missing` : "Complete"}
                            </span>
                          </div>
                          {Object.keys(doc.fields).length > 0 && (
                            <div className="mt-3 grid gap-2 sm:grid-cols-2">
                              {Object.entries(doc.fields).map(([key, value]) => (
                                <DocFieldChip key={key} label={key} value={value} />
                              ))}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </Panel>
                  )}
                </div>

              </>
            ) : (
              <EmptyState title="No claim submitted yet" body="Upload a document and submit a claim to populate the review panels." />
            )}
          </div>
        </section>
        ) : null}

        {view === "decision" ? (
        <section className="grid scroll-mt-32 gap-6 xl:grid-cols-2" id="decision-trace-section">
          {claimResponse ? (
            <>
              <Panel title="Trace timeline" icon={<Clock3 className="h-4 w-4" />}>
                <div className="space-y-2">
                  {(claimResponse.trace?.length ?? 0) > 0 ? (
                    claimResponse.trace?.map((event, index) => (
                      <div key={`${event.component}-${index}`} className={`flex gap-3 rounded-[16px] border p-4 ${
                        event.level === "WARNING" ? "border-[#f5d98a] bg-[#fffbf0]"
                        : event.level === "ERROR" ? "border-[#f1c4c0] bg-[#fff5f5]"
                        : "border-[color:var(--line)] bg-[#fffaf2]"
                      }`}>
                        <div className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[10px] font-bold text-white ${
                          event.level === "WARNING" ? "bg-[#d97706]"
                          : event.level === "ERROR" ? "bg-[#dc2626]"
                          : "bg-[var(--plum)]"
                        }`}>
                          {index + 1}
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <p className="text-sm font-semibold text-[var(--ink)]">{event.component}</p>
                            <span className={`rounded-full px-2 py-0.5 text-[9px] font-semibold uppercase tracking-[0.15em] ${
                              event.level === "WARNING" ? "bg-[#fef3c7] text-[#92400e]"
                              : event.level === "ERROR" ? "bg-[#fee2e2] text-[#991b1b]"
                              : "bg-[#dcfce7] text-[#166534]"
                            }`}>
                              {event.level}
                            </span>
                            {typeof event.confidence_impact === "number" && event.confidence_impact !== 0 && (
                              <span className={`text-[10px] font-semibold tabular-nums ${event.confidence_impact > 0 ? "text-[#16a34a]" : "text-[#dc2626]"}`}>
                                {event.confidence_impact > 0 ? "+" : ""}{(event.confidence_impact * 100).toFixed(1)}%
                              </span>
                            )}
                          </div>
                          <p className="mt-1 text-sm leading-5 text-[var(--muted)]">{event.message}</p>
                        </div>
                      </div>
                    ))
                  ) : (
                    <EmptyState title="No trace yet" body="Run a submission to populate the trace timeline." />
                  )}
                </div>
              </Panel>

              <Panel title="Policy evidence & warnings" icon={<Hospital className="h-4 w-4" />}>
                <div className="space-y-5">
                  <div className="space-y-2">
                    <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--muted)]">Retrieved evidence</p>
                    {(() => {
                      const policyEvidence = (claimResponse.retrieved_policy_evidence ?? []).filter(
                        (e) => !e.source.toLowerCase().includes("sample_documents_guide") && e.rule_category !== "document_extraction"
                      );
                      return policyEvidence.length > 0 ? (
                        policyEvidence.map((evidence) => {
                          // Parse: "{description}. JSON path: key {json...}"
                          const jpIdx = evidence.text.indexOf("JSON path:");
                          const description = jpIdx !== -1
                            ? evidence.text.slice(0, jpIdx).trim().replace(/\.$/, "")
                            : evidence.text.slice(0, 160).trim();
                          let jsonData: unknown = null;
                          if (jpIdx !== -1) {
                            const rest = evidence.text.slice(jpIdx + 10).trim();
                            const jStart = rest.search(/[{[]/);
                            if (jStart !== -1) {
                              try { jsonData = JSON.parse(rest.slice(jStart)); } catch { /* leave null */ }
                            }
                          }
                          return (
                            <div key={evidence.evidence_id} className="rounded-[16px] border border-[color:var(--line)] bg-[#fffaf2] p-4">
                              <div className="flex items-center justify-between gap-3">
                                <p className="text-sm font-semibold capitalize text-[var(--ink)]">{evidence.rule_category.replace(/_/g, " ")}</p>
                                {typeof evidence.rrf_score === "number" && (
                                  <span className="shrink-0 rounded-full bg-white px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.15em] text-[var(--muted)]">
                                    {evidence.rrf_score.toFixed(3)}
                                  </span>
                                )}
                              </div>
                              {description && (
                                <p className="mt-1 text-xs leading-5 text-[var(--muted)]">{description}</p>
                              )}
                              {jsonData !== null && <PolicyDataDisplay data={jsonData} />}
                            </div>
                          );
                        })
                      ) : (
                        <EmptyState title="No policy evidence" body="The response did not include retrieved evidence." />
                      );
                    })()}
                  </div>

                  {(claimResponse.component_failures?.length ?? 0) > 0 && (
                    <div className="space-y-2">
                      <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--muted)]">Component failures</p>
                      {claimResponse.component_failures?.map((failure) => (
                        <div key={`${failure.component}-${failure.message}`} className="rounded-[16px] border border-[#f1c4c0] bg-[#fff5f5] p-4">
                          <div className="flex items-center gap-2">
                            <AlertCircle className="h-4 w-4 shrink-0 text-[#dc2626]" />
                            <p className="text-sm font-semibold text-[#7f1d1d]">{failure.component}</p>
                          </div>
                          <p className="mt-2 text-sm leading-6 text-[#9c3b34]">{failure.message}</p>
                        </div>
                      ))}
                    </div>
                  )}

                  {claimResponse.member_action_required && (
                    <div className="space-y-2">
                      <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--muted)]">Member action required</p>
                      <div className="rounded-[16px] border border-[#f5d0a9] bg-[#fff8f0] p-4">
                        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#9f5f17]">{claimResponse.member_action_required.code.replace(/_/g, " ")}</p>
                        <p className="mt-2 whitespace-pre-line text-sm leading-6 text-[#a06a2a]">{claimResponse.member_action_required.message}</p>
                      </div>
                    </div>
                  )}
                </div>
              </Panel>
            </>
          ) : (
            <div className="xl:col-span-2">
              <EmptyState title="No claim submitted yet" body="Upload a document and submit a claim to populate the trace timeline." />
            </div>
          )}
        </section>
        ) : null}

        {view === "eval" ? (
        <section id="eval-section" className="grid scroll-mt-32 gap-6 xl:grid-cols-[0.82fr_1.18fr]">
          <Panel title="Eval dashboard" icon={<BarChart3 className="h-4 w-4" />}>
            <div className="space-y-4">
              {evalRun && (
                <div className="rounded-[14px] border border-[color:var(--line)] bg-[#fffaf2] p-3 text-xs text-[var(--muted)]">
                  <span className="font-semibold text-[var(--ink)]">{evalRun.eval_run_id}</span>
                  {" · "}
                  {evalRun.metrics.completed_cases}/{evalRun.metrics.total_cases} cases
                  {evalRun.completed_at && ` · ${new Date(evalRun.completed_at).toLocaleTimeString("en-IN")}`}
                </div>
              )}

              <div className="grid gap-3 sm:grid-cols-2">
                {([
                  ["Decision accuracy", evalRun?.metrics.decision_accuracy, "Correct decision type out of all cases"],
                  ["Early stop accuracy", evalRun?.metrics.early_stop_accuracy, "ACTION_REQUIRED returned correctly before adjudication"],
                  ["Amount exact match", evalRun?.metrics.approved_amount_exact_match_rate, "Approved amount matches expected exactly"],
                  ["System must accuracy", evalRun?.metrics.system_must_accuracy, "All system_must behavioural requirements satisfied"],
                  ["Rejection reason F1", evalRun?.metrics.rejection_reason_f1, "Label-level F1 on rejection reason codes (4 cases)"],
                  ["Rejection reason precision", evalRun?.metrics.rejection_reason_precision, "Macro-avg precision over rejection label codes"],
                ] as [string, number | null | undefined, string][]).map(([label, value, description]) => (
                  <div key={label} className="rounded-[18px] border border-[color:var(--line)] bg-[#fffaf2] p-4">
                    <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[var(--muted)]">{label}</p>
                    <p className={`mt-2 text-2xl font-semibold ${typeof value === "number" ? (value >= 0.9 ? "text-[#1f8f5c]" : value >= 0.7 ? "text-[#9f5f17]" : "text-[#a83d35]") : "text-[var(--muted)]"}`}>
                      {typeof value === "number" ? `${Math.round(value * 100)}%` : "—"}
                    </p>
                    <p className="mt-1 text-xs text-[var(--muted)]">{description}</p>
                  </div>
                ))}
              </div>

              <button
                type="button"
                onClick={() => startTransition(() => handleRunEval())}
                className="inline-flex items-center gap-2 rounded-full bg-[var(--plum)] px-4 py-3 text-sm font-semibold text-white transition hover:opacity-95"
              >
                {loading === "eval" ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                Run all 12 test cases
              </button>

              <div className="rounded-[18px] border border-[color:var(--line)] bg-white p-4">
                <Image
                  src="/plum-assets/admin-experience.png"
                  alt="Plum admin experience reference"
                  width={960}
                  height={540}
                  className="h-auto w-full rounded-[16px] border border-[color:var(--line)] object-cover"
                />
                <p className="mt-3 text-sm leading-6 text-[var(--muted)]">
                  The layout borrows Plum's warm editorial polish, then leans into ops density so
                  the assessment still feels like a working internal tool.
                </p>
              </div>
            </div>
          </Panel>

          <Panel title="Case results" icon={<Menu className="h-4 w-4" />}>
              <div className="overflow-hidden rounded-[18px] border border-[color:var(--line)] bg-white">
                <div className="grid grid-cols-12 border-b border-[color:var(--line)] bg-[#fffaf2] px-4 py-3 text-xs font-semibold uppercase tracking-[0.18em] text-[var(--muted)]">
                  <div className="col-span-2">Case</div>
                  <div className="col-span-3">Expected</div>
                  <div className="col-span-3">Actual</div>
                  <div className="col-span-2">Result</div>
                  <div className="col-span-2 text-right">Trace</div>
                </div>
                <div className="divide-y divide-[color:var(--line)]">
                  {evalRun?.cases.length ? (
                    evalRun.cases.map((item) => {
                      const isExpanded = expandedCaseId === item.case_id;
                      const actualDecision = item.actual?.decision?.decision ?? item.actual?.status ?? "N/A";
                      const actualAmount = item.actual?.decision?.approved_amount ?? item.actual?.approved_amount;
                      const expectedAmount = typeof item.expected.approved_amount === "number" ? item.expected.approved_amount : null;
                      const amountMismatch = expectedAmount !== null && typeof actualAmount === "number" && Math.abs(actualAmount - expectedAmount) > 0.01;
                      return (
                        <div key={item.case_id}>
                          <button
                            type="button"
                            onClick={() => setExpandedCaseId(isExpanded ? null : item.case_id)}
                            className="grid w-full grid-cols-12 gap-3 px-4 py-4 text-left transition hover:bg-[#fdf8f4]"
                          >
                            <div className="col-span-2">
                              <div className="text-sm font-semibold text-[var(--ink)]">{item.case_id}</div>
                              <div className="mt-0.5 text-xs text-[var(--muted)]">{item.case_name}</div>
                            </div>
                            <div className="col-span-3 text-sm text-[var(--muted)]">
                              {stringifyExpectation(item.expected)}
                            </div>
                            <div className="col-span-3">
                              <div className="text-sm text-[var(--muted)]">{actualDecision}</div>
                              {typeof actualAmount === "number" && (
                                <div className={`mt-0.5 text-xs font-medium ${amountMismatch ? "text-[#a83d35]" : "text-[#1f8f5c]"}`}>
                                  INR {actualAmount.toLocaleString("en-IN")}
                                </div>
                              )}
                            </div>
                            <div className="col-span-2">
                              <ResultBadge passed={item.passed ?? true} />
                            </div>
                            <div className="col-span-2 flex items-center justify-end gap-1 text-sm font-medium text-[var(--plum)]">
                              {isExpanded ? "Hide" : "Trace"}
                              <ArrowRight className={`h-3.5 w-3.5 transition-transform ${isExpanded ? "rotate-90" : ""}`} />
                            </div>
                          </button>
                          {isExpanded && (
                            <div className="border-t border-[color:var(--line)] bg-[#fdf8f4] px-4 pb-5 pt-4 space-y-4">
                              {/* Notes */}
                              {item.notes.length > 0 && (
                                <div className="space-y-1.5">
                                  <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--muted)]">Evaluator notes</p>
                                  {item.notes.map((note, noteIndex) => (
                                    <div key={noteIndex} className="flex items-start gap-2 text-sm text-[var(--muted)]">
                                      <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--plum)]" />
                                      {note}
                                    </div>
                                  ))}
                                </div>
                              )}
                              {/* Expected vs actual side-by-side */}
                              <div className="grid gap-3 sm:grid-cols-2">
                                <div className="rounded-[14px] border border-[color:var(--line)] bg-white p-3">
                                  <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--muted)]">Expected</p>
                                  <div className="mt-2 space-y-1">
                                    {Object.entries(item.expected).map(([k, v]) => (
                                      <div key={k} className="flex items-center justify-between gap-2 text-xs">
                                        <span className="text-[var(--muted)]">{k.replace(/_/g, " ")}</span>
                                        <span className="font-medium text-[var(--ink)]">{String(v)}</span>
                                      </div>
                                    ))}
                                  </div>
                                </div>
                                <div className="rounded-[14px] border border-[color:var(--line)] bg-white p-3">
                                  <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--muted)]">Actual</p>
                                  <div className="mt-2 space-y-1">
                                    <div className="flex items-center justify-between gap-2 text-xs">
                                      <span className="text-[var(--muted)]">decision</span>
                                      <span className="font-medium text-[var(--ink)]">{actualDecision}</span>
                                    </div>
                                    {typeof actualAmount === "number" && (
                                      <div className="flex items-center justify-between gap-2 text-xs">
                                        <span className="text-[var(--muted)]">approved amount</span>
                                        <span className={`font-medium ${amountMismatch ? "text-[#a83d35]" : "text-[var(--ink)]"}`}>
                                          INR {actualAmount.toLocaleString("en-IN")}
                                        </span>
                                      </div>
                                    )}
                                    {typeof item.actual?.confidence_score === "number" && (
                                      <div className="flex items-center justify-between gap-2 text-xs">
                                        <span className="text-[var(--muted)]">confidence</span>
                                        <span className="font-medium text-[var(--ink)]">{Math.round(item.actual.confidence_score * 100)}%</span>
                                      </div>
                                    )}
                                    {item.actual?.status && (
                                      <div className="flex items-center justify-between gap-2 text-xs">
                                        <span className="text-[var(--muted)]">status</span>
                                        <span className="font-medium text-[var(--ink)]">{item.actual.status}</span>
                                      </div>
                                    )}
                                  </div>
                                </div>
                              </div>
                              {/* Trace events */}
                              {(item.actual?.trace?.length ?? 0) > 0 && (
                                <div className="space-y-2">
                                  <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--muted)]">Trace timeline</p>
                                  <div className="space-y-2">
                                    {item.actual?.trace?.map((event, eventIndex) => (
                                      <div key={`${event.component}-${eventIndex}`} className="flex gap-3 rounded-[14px] border border-[color:var(--line)] bg-white p-3">
                                        <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[var(--plum)] text-[10px] font-bold text-white">
                                          {eventIndex + 1}
                                        </div>
                                        <div className="min-w-0 flex-1">
                                          <div className="flex flex-wrap items-center gap-2">
                                            <span className="text-xs font-semibold text-[var(--ink)]">{event.component}</span>
                                            <span className={`rounded-full px-2 py-0.5 text-[9px] font-semibold uppercase tracking-[0.14em] ${
                                              event.level === "WARNING" ? "bg-[#fff1db] text-[#9f5f17]"
                                              : event.level === "ERROR" ? "bg-[#ffe0dd] text-[#a83d35]"
                                              : "bg-[#e7f4ee] text-[#1f8f5c]"
                                            }`}>{event.level}</span>
                                            {typeof event.confidence_impact === "number" && event.confidence_impact !== 0 && (
                                              <span className={`text-[9px] font-semibold ${event.confidence_impact > 0 ? "text-[#1f8f5c]" : "text-[#a83d35]"}`}>
                                                {event.confidence_impact > 0 ? "+" : ""}{(event.confidence_impact * 100).toFixed(1)}%
                                              </span>
                                            )}
                                          </div>
                                          <p className="mt-1 text-xs leading-5 text-[var(--muted)]">{event.message}</p>
                                        </div>
                                      </div>
                                    ))}
                                  </div>
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      );
                    })
                  ) : (
                    <div className="p-4">
                      <EmptyState title="No eval results yet" body="Run the backend eval suite to populate test case results." />
                    </div>
                  )}
                </div>
              </div>
            </Panel>
        </section>
        ) : null}
        </div>
      </div>
    </main>
  );
}

function Panel({
  title,
  icon,
  children
}: {
  title: string;
  icon: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="overflow-hidden rounded-[24px] border border-[color:var(--line)] bg-white shadow-[0_18px_60px_rgba(29,7,22,0.05)]">
      <div className="flex items-center justify-between border-b border-[color:var(--line)] bg-[#fffaf2] px-5 py-4">
        <div className="flex items-center gap-2">
          <span className="flex h-8 w-8 items-center justify-center rounded-full bg-[var(--plum)] text-white">{icon}</span>
          <h2 className="text-base font-semibold text-[var(--ink)]">{title}</h2>
        </div>
      </div>
      <div className="p-5">{children}</div>
    </section>
  );
}

function Field({
  label,
  children
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <label className="flex flex-col gap-2 text-sm">
      <span className="font-medium text-[var(--ink)]">{label}</span>
      {children}
    </label>
  );
}

function Pill({
  icon,
  label
}: {
  icon: ReactNode;
  label: string;
}) {
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-[color:var(--line)] bg-white px-3 py-2 text-sm font-medium text-[var(--ink)]">
      <span className="text-[var(--plum)]">{icon}</span>
      {label}
    </span>
  );
}

function DecisionBadge({ decision }: { decision: DecisionType }) {
  const palette = {
    APPROVED: "bg-[#e9f6ef] text-[#1f8f5c]",
    PARTIAL: "bg-[#fff0dc] text-[#9f5f17]",
    REJECTED: "bg-[#ffe2df] text-[#a83d35]",
    MANUAL_REVIEW: "bg-[#ede8ff] text-[#4e399f]"
  } as const;

  return <span className={`inline-flex rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-[0.15em] ${palette[decision]}`}>{decision.replace("_", " ")}</span>;
}

function LineBadge({ decision }: { decision: "APPROVED" | "REJECTED" | "ADJUSTED" | "REVIEW" }) {
  const palette = {
    APPROVED: "bg-[#e9f6ef] text-[#1f8f5c]",
    REJECTED: "bg-[#ffe2df] text-[#a83d35]",
    ADJUSTED: "bg-[#fff0dc] text-[#9f5f17]",
    REVIEW: "bg-[#ede8ff] text-[#4e399f]"
  } as const;
  return <span className={`inline-flex rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-[0.15em] ${palette[decision]}`}>{decision}</span>;
}

function ResultBadge({ passed }: { passed: boolean }) {
  return (
    <span className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-[0.15em] ${
      passed ? "bg-[#e9f6ef] text-[#1f8f5c]" : "bg-[#ffe2df] text-[#a83d35]"
    }`}>
      {passed ? <CheckCircle2 className="h-3.5 w-3.5" /> : <XCircle className="h-3.5 w-3.5" />}
      {passed ? "Pass" : "Fail"}
    </span>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[18px] border border-[color:var(--line)] bg-[#fffaf2] p-4">
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[var(--muted)]">{label}</p>
      <p className="mt-2 whitespace-pre-line text-sm leading-6 text-[var(--ink)]">{value}</p>
    </div>
  );
}

function PolicyDataDisplay({ data }: { data: unknown }) {
  // Array of strings → tag list
  if (Array.isArray(data) && data.every((v) => typeof v === "string")) {
    const items = data as string[];
    const show = items.slice(0, 8);
    const extra = items.length - show.length;
    return (
      <div className="mt-2 flex flex-wrap gap-1.5">
        {show.map((s, i) => (
          <span key={i} className="rounded-full bg-white border border-[color:var(--line)] px-2.5 py-0.5 text-xs font-medium text-[var(--ink)]">{s}</span>
        ))}
        {extra > 0 && (
          <span className="rounded-full bg-[#f3ede8] px-2.5 py-0.5 text-xs font-medium text-[var(--muted)]">+{extra} more</span>
        )}
      </div>
    );
  }
  // Object → key-value grid
  if (data !== null && typeof data === "object" && !Array.isArray(data)) {
    const entries = Object.entries(data as Record<string, unknown>);
    return (
      <div className="mt-2 grid gap-x-4 gap-y-1.5 sm:grid-cols-2">
        {entries.map(([k, v]) => {
          const label = k.replace(/_/g, " ");
          let display: React.ReactNode;
          if (v === null || v === undefined) {
            display = <span className="text-[var(--muted)]">—</span>;
          } else if (Array.isArray(v)) {
            const strs = v.map(String);
            const shown = strs.slice(0, 4).join(", ");
            display = (
              <span>{shown}{strs.length > 4 ? ` +${strs.length - 4} more` : ""}</span>
            );
          } else if (typeof v === "object") {
            display = <span className="text-[var(--muted)]">{Object.keys(v as object).length} fields</span>;
          } else if (typeof v === "boolean") {
            display = (
              <span className={v ? "text-[#1f8f5c]" : "text-[#dc2626]"}>{v ? "Yes" : "No"}</span>
            );
          } else {
            const s = String(v);
            display = <span>{s.length > 60 ? s.slice(0, 60) + "…" : s}</span>;
          }
          return (
            <div key={k} className="flex gap-1.5 text-xs">
              <span className="shrink-0 font-semibold capitalize text-[var(--ink)]">{label}:</span>
              <span className="text-[var(--muted)]">{display}</span>
            </div>
          );
        })}
      </div>
    );
  }
  return <p className="mt-2 text-xs text-[var(--muted)]">{String(data)}</p>;
}

function DocFieldChip({ label, value }: { label: string; value: unknown }) {
  const isLongString = typeof value === "string" && value.length > 80 && value.includes(", ");
  const isComplex = Array.isArray(value) || (value !== null && typeof value === "object") || isLongString;

  const renderContent = () => {
    if (value === null || value === undefined) {
      return <p className="mt-1 text-sm font-medium text-[var(--ink)]">—</p>;
    }
    if (Array.isArray(value)) {
      // Array of objects with description/amount (line_items)
      if (value.length > 0 && typeof value[0] === "object" && value[0] !== null) {
        return (
          <ul className="mt-1 space-y-1">
            {(value as Record<string, unknown>[]).map((item, i) => {
              const desc = item.description ?? item.name ?? item.item ?? Object.values(item)[0];
              const amt = item.amount ?? item.price ?? item.cost ?? item.value ?? Object.values(item)[1];
              const hasAmt = amt !== undefined && amt !== null;
              return (
                <li key={i} className="text-sm text-[var(--ink)]">
                  <span className="text-[var(--muted)]">•</span>{" "}
                  {String(desc ?? JSON.stringify(item))}
                  {hasAmt && <span className="ml-1 font-medium">— INR {Number(amt).toLocaleString("en-IN")}</span>}
                </li>
              );
            })}
          </ul>
        );
      }
      // Array of scalars
      return (
        <p className="mt-1 text-sm text-[var(--ink)]">
          {(value as unknown[]).map(String).join(", ")}
        </p>
      );
    }
    if (typeof value === "object") {
      return (
        <ul className="mt-1 space-y-0.5">
          {Object.entries(value as Record<string, unknown>).map(([k, v]) => (
            <li key={k} className="text-sm text-[var(--ink)]">
              <span className="font-medium">{k}:</span> {String(v ?? "—")}
            </li>
          ))}
        </ul>
      );
    }
    // Long comma-separated string — try to parse as lab test entries
    const str = String(value);
    if (str.length > 80 && str.includes(", ")) {
      const items = str.split(/, /);
      const isNum = (s: string) => /^\d/.test(s.trim());
      const isTestName = (s: string, nextS?: string) =>
        /^[A-Za-z\u0080-\uFFFF]/.test(s.trim()) && s.trim().length > 1 && !!nextS && isNum(nextS);

      // Collect test entries: {name, value, unit, range}
      type TestRow = { name: string; val: string; unit: string; range: string };
      const rows: TestRow[] = [];
      let i = 0;
      // Skip header items (e.g. "Result, Unit, Normal Range, Flag")
      while (i < items.length && !isTestName(items[i], items[i + 1])) i++;

      while (i < items.length) {
        const name = items[i].trim();
        i++;
        const vals: string[] = [];
        while (i < items.length && !isTestName(items[i], items[i + 1])) {
          vals.push(items[i].trim());
          i++;
        }
        if (vals.length > 0) {
          const val = vals[0];
          const range = vals.find((v) => v.includes("–") || (v.includes("-") && v.length > 3)) ?? "";
          const unitParts = vals.slice(1).filter((v) => !v.includes("–") && !(v.includes("-") && v.length > 3) && !isNum(v)).slice(0, 2);
          rows.push({ name, val, unit: unitParts.join("/"), range });
        }
      }

      if (rows.length > 1) {
        return (
          <div className="mt-1 max-h-44 overflow-y-auto">
            <table className="w-full text-xs">
              <tbody>
                {rows.map((row, idx) => (
                  <tr key={idx} className="border-b border-[color:var(--line)] last:border-0">
                    <td className="py-1 pr-3 font-medium text-[var(--ink)]">{row.name}</td>
                    <td className="py-1 pr-2 text-right font-semibold text-[var(--ink)]">{row.val}{row.unit ? ` ${row.unit}` : ""}</td>
                    {row.range && <td className="py-1 text-right text-[var(--muted)]">{row.range}</td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      }
    }
    return <p className="mt-1 text-sm font-medium text-[var(--ink)]">{str}</p>;
  };

  return (
    <div className={`rounded-[14px] border border-[color:var(--line)] bg-white px-3 py-2 ${isComplex ? "sm:col-span-2" : ""}`}>
      <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[var(--muted)]">{label}</p>
      {renderContent()}
    </div>
  );
}

function DetailChip({ label, value }: { label: string; value: string }) {
  const isJson = value.startsWith("[") || value.startsWith("{");
  return (
    <div className={`rounded-[14px] border border-[color:var(--line)] bg-white px-3 py-2 ${isJson ? "sm:col-span-2" : ""}`}>
      <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[var(--muted)]">{label}</p>
      {isJson ? (
        <pre className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap break-all font-mono text-xs text-[var(--ink)]">{value}</pre>
      ) : (
        <p className="mt-1 text-sm font-medium text-[var(--ink)]">{value}</p>
      )}
    </div>
  );
}

function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-[18px] border border-dashed border-[color:var(--line)] bg-[#fffaf2] p-5">
      <p className="text-sm font-semibold text-[var(--ink)]">{title}</p>
      <p className="mt-1 text-sm leading-6 text-[var(--muted)]">{body}</p>
    </div>
  );
}

function stringifyExpectation(value: Record<string, unknown>) {
  const decision = value.decision;
  const approvedAmount = value.approved_amount;
  if (decision && approvedAmount) {
    return `${String(decision)} · INR ${String(approvedAmount)}`;
  }
  if (decision) return String(decision);
  return "Expected outcome";
}
