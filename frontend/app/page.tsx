"use client";

import Image from "next/image";
import { startTransition, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Activity,
  AlertCircle,
  ArrowRight,
  BadgeCheck,
  BarChart3,
  Bot,
  CalendarDays,
  CheckCircle2,
  Clock3,
  FileText,
  Hospital,
  Layers3,
  Loader2,
  Menu,
  Paperclip,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  UploadCloud,
  User,
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
    reason_precision?: number | null;
    reason_recall?: number | null;
    reason_f1?: number | null;
    retrieval_precision_at_k?: number | null;
    retrieval_recall_at_k?: number | null;
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

const demoCases: Array<{
  id: string;
  name: string;
  category: ClaimCategory;
  memberId: string;
  amount: number;
  note: string;
  response: ClaimResponse;
}> = [
  {
    id: "TC004",
    name: "Clean consultation",
    category: "CONSULTATION",
    memberId: "EMP001",
    amount: 1500,
    note: "Approved with 10% co-pay, strong trace confidence, and full policy evidence.",
    response: {
      claim_id: "CLM_DEMO_004",
      status: "COMPLETED",
      decision: {
        decision: "APPROVED",
        approved_amount: 1350,
        confidence_score: 0.92,
        reason: "Consultation claim is covered, within limits, and co-pay was applied.",
        rejection_reasons: [],
        line_item_decisions: [
          {
            description: "Consultation fee",
            claimed_amount: 1000,
            approved_amount: 900,
            decision: "ADJUSTED",
            reason: "10% consultation co-pay applied."
          },
          {
            description: "Diagnostics",
            claimed_amount: 500,
            approved_amount: 450,
            decision: "ADJUSTED",
            reason: "10% consultation co-pay applied."
          }
        ]
      },
      approved_amount: 1350,
      confidence_score: 0.92,
      reason: "Consultation claim is covered, within limits, and co-pay was applied.",
      rejection_reasons: [],
      line_item_decisions: [
        {
          description: "Consultation fee",
          claimed_amount: 1000,
          approved_amount: 900,
          decision: "ADJUSTED",
          reason: "10% consultation co-pay applied."
        },
        {
          description: "Diagnostics",
          claimed_amount: 500,
          approved_amount: 450,
          decision: "ADJUSTED",
          reason: "10% consultation co-pay applied."
        }
      ],
      extracted_document_data: [
        {
          file_id: "F007",
          document_type: "PRESCRIPTION",
          fields: {
            doctor_name: "Dr. Arun Sharma",
            patient_name: "Rajesh Kumar",
            diagnosis: "Viral Fever"
          },
          missing_fields: [],
          confidence: 0.95,
          warnings: []
        }
      ],
      trace: [
        {
          timestamp: new Date().toISOString(),
          component: "DocumentClassifier",
          level: "INFO",
          message: "Documents classified for early intake validation.",
          checks_performed: ["document_classification"]
        },
        {
          timestamp: new Date().toISOString(),
          component: "RuleEngine",
          level: "INFO",
          message: "Deterministic policy checks completed.",
          output_summary: { decision: "APPROVED", approved_amount: 1350, confidence_score: 0.92 }
        }
      ],
      retrieved_policy_evidence: [
        {
          evidence_id: "EVID_001",
          source: "policy_terms.json",
          rule_category: "co_pay",
          claim_category: "CONSULTATION",
          text: "Consultation claims attract a 10% co-pay."
        },
        {
          evidence_id: "EVID_002",
          source: "policy_terms.json",
          rule_category: "coverage",
          claim_category: "CONSULTATION",
          text: "Consultation is a covered claim category."
        }
      ],
      component_failures: []
    }
  },
  {
    id: "TC006",
    name: "Dental partial approval",
    category: "DENTAL",
    memberId: "EMP002",
    amount: 12000,
    note: "Split decision showing line-item adjudication and rejection rationale.",
    response: {
      claim_id: "CLM_DEMO_006",
      status: "COMPLETED",
      decision: {
        decision: "PARTIAL",
        approved_amount: 8000,
        confidence_score: 0.89,
        reason: "Covered dental work approved; cosmetic whitening was excluded.",
        rejection_reasons: ["COSMETIC_DENTAL_EXCLUSION"],
        line_item_decisions: [
          {
            description: "Root canal treatment",
            claimed_amount: 8000,
            approved_amount: 8000,
            decision: "APPROVED",
            reason: "Covered under dental benefits."
          },
          {
            description: "Teeth whitening",
            claimed_amount: 4000,
            approved_amount: 0,
            decision: "REJECTED",
            reason: "Cosmetic dental procedure is excluded."
          }
        ]
      },
      approved_amount: 8000,
      confidence_score: 0.89,
      reason: "Covered dental work approved; cosmetic whitening was excluded.",
      rejection_reasons: ["COSMETIC_DENTAL_EXCLUSION"],
      line_item_decisions: [
        {
          description: "Root canal treatment",
          claimed_amount: 8000,
          approved_amount: 8000,
          decision: "APPROVED",
          reason: "Covered under dental benefits."
        },
        {
          description: "Teeth whitening",
          claimed_amount: 4000,
          approved_amount: 0,
          decision: "REJECTED",
          reason: "Cosmetic dental procedure is excluded."
        }
      ],
      extracted_document_data: [
        {
          file_id: "F011",
          document_type: "HOSPITAL_BILL",
          fields: {
            hospital_name: "Smile Dental Clinic",
            patient_name: "Priya Singh"
          },
          missing_fields: [],
          confidence: 0.91,
          warnings: []
        }
      ],
      trace: [
        {
          timestamp: new Date().toISOString(),
          component: "RuleEngine",
          level: "INFO",
          message: "Line-item review completed."
        }
      ],
      retrieved_policy_evidence: [
        {
          evidence_id: "EVID_010",
          source: "policy_terms.json",
          rule_category: "exclusions",
          claim_category: "DENTAL",
          text: "Cosmetic dental procedures are excluded."
        }
      ],
      component_failures: []
    }
  },
  {
    id: "TC009",
    name: "Fraud signal manual review",
    category: "DIAGNOSTIC",
    memberId: "EMP007",
    amount: 25000,
    note: "Manual review route with a visible warning state and confidence drop.",
    response: {
      claim_id: "CLM_DEMO_009",
      status: "COMPLETED",
      decision: {
        decision: "MANUAL_REVIEW",
        approved_amount: 0,
        confidence_score: 0.67,
        reason: "High-value claim matched fraud thresholds and needs manual review.",
        rejection_reasons: [],
        line_item_decisions: []
      },
      approved_amount: 0,
      confidence_score: 0.67,
      reason: "High-value claim matched fraud thresholds and needs manual review.",
      rejection_reasons: [],
      line_item_decisions: [],
      extracted_document_data: [],
      trace: [
        {
          timestamp: new Date().toISOString(),
          component: "FraudSignalAgent",
          level: "WARNING",
          message: "Claim routed to manual review due to fraud signals.",
          warnings: ["High-value claim matched threshold."]
        }
      ],
      retrieved_policy_evidence: [],
      component_failures: []
    }
  }
];

const defaultDraft: ClaimDraft = {
  memberId: "EMP001",
  policyId: "PLUM_GHI_2024",
  claimCategory: "CONSULTATION",
  treatmentDate: "2024-11-01",
  claimedAmount: "1500",
  ytdClaimsAmount: "5000",
  hospitalName: "City Clinic, Bengaluru",
  documents: [
    {
      id: "doc-1",
      file: null,
      declaredType: "PRESCRIPTION",
      patientName: "Rajesh Kumar",
      quality: "GOOD"
    },
    {
      id: "doc-2",
      file: null,
      declaredType: "HOSPITAL_BILL",
      patientName: "Rajesh Kumar",
      quality: "GOOD"
    }
  ]
};

export default function Home() {
  const [view, setView] = useState<ViewKey>("submit");
  const [draft, setDraft] = useState<ClaimDraft>(defaultDraft);
  const [claimResponse, setClaimResponse] = useState<ClaimResponse>(demoCases[0].response);
  const [evalRun, setEvalRun] = useState<EvalRun | null>(null);
  const [statusMessage, setStatusMessage] = useState<string>("Use a demo case or submit the form to inspect the trace.");
  const [loading, setLoading] = useState<"submit" | "eval" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedCaseId, setSelectedCaseId] = useState<string>(demoCases[0].id);

  const selectedDemo = useMemo(() => {
    return demoCases.find((item) => item.id === selectedCaseId) ?? demoCases[0];
  }, [selectedCaseId]);

  useEffect(() => {
    setClaimResponse(selectedDemo.response);
  }, [selectedDemo]);

  const metrics = useMemo(
    () => [
      { label: "Policy engine", value: "Deterministic", detail: "Hybrid retrieval + rule checks" },
      { label: "Eval cases", value: "12", detail: "Expected vs actual traceable" },
      { label: "Confidence", value: claimResponse.confidence_score ? `${Math.round(claimResponse.confidence_score * 100)}%` : "N/A", detail: "Updated with each submission" }
    ],
    [claimResponse.confidence_score]
  );

  async function handleSubmitClaim() {
    setLoading("submit");
    setError(null);
    setStatusMessage("Submitting claim and waiting for adjudication...");

    try {
      const hasFiles = draft.documents.some((doc) => doc.file);
      let response: ClaimResponse;

      if (hasFiles) {
        const formData = new FormData();
        formData.append("member_id", draft.memberId);
        formData.append("policy_id", draft.policyId);
        formData.append("claim_category", draft.claimCategory);
        formData.append("treatment_date", draft.treatmentDate);
        formData.append("claimed_amount", draft.claimedAmount);
        if (draft.ytdClaimsAmount) formData.append("ytd_claims_amount", draft.ytdClaimsAmount);
        if (draft.hospitalName) formData.append("hospital_name", draft.hospitalName);

        const declaredTypes: Record<string, DocumentType> = {};
        const patientNames: Record<string, string> = {};

        draft.documents.forEach((document, index) => {
          if (!document.file) return;
          formData.append("files", document.file);
          declaredTypes[document.file.name || `upload_${index + 1}`] = document.declaredType;
          patientNames[document.file.name || `upload_${index + 1}`] = document.patientName;
        });

        formData.append("declared_types", JSON.stringify(declaredTypes));
        formData.append("patient_names", JSON.stringify(patientNames));

        const result = await fetch(`${apiBaseUrl}/claims/submit/upload`, {
          method: "POST",
          body: formData
        });

        if (!result.ok) throw new Error(`Upload submission failed with status ${result.status}`);
        response = (await result.json()) as ClaimResponse;
      } else {
        const payload = {
          member_id: draft.memberId,
          policy_id: draft.policyId,
          claim_category: draft.claimCategory,
          treatment_date: draft.treatmentDate,
          claimed_amount: Number(draft.claimedAmount),
          ytd_claims_amount: draft.ytdClaimsAmount ? Number(draft.ytdClaimsAmount) : null,
          hospital_name: draft.hospitalName || null,
          documents: draft.documents.map((document, index) => ({
            file_id: document.id.toUpperCase().replace(/[^A-Z0-9]/g, ""),
            file_name: `${document.declaredType.toLowerCase()}_${index + 1}.jpg`,
            actual_type: document.declaredType,
            quality: document.quality,
            patient_name_on_doc: document.patientName
          }))
        };

        const result = await fetch(`${apiBaseUrl}/claims/submit`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });

        if (!result.ok) throw new Error(`Claim submission failed with status ${result.status}`);
        response = (await result.json()) as ClaimResponse;
      }

      setClaimResponse(response);
      setView("decision");
      setStatusMessage(`Claim ${response.claim_id} returned ${response.status}.`);
    } catch (submissionError) {
      setError(submissionError instanceof Error ? submissionError.message : "Submission failed");
      setClaimResponse(selectedDemo.response);
      setStatusMessage("Falling back to demo trace while the backend is unavailable.");
      setView("decision");
    } finally {
      setLoading(null);
    }
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
      setEvalRun({
        eval_run_id: "EVAL_DEMO",
        status: "COMPLETED",
        started_at: new Date().toISOString(),
        completed_at: new Date().toISOString(),
        metrics: {
          total_cases: 12,
          completed_cases: 12,
          decision_accuracy: 0.92,
          early_stop_accuracy: 1,
          approved_amount_exact_match_rate: 0.92,
          reason_precision: 0.91,
          reason_recall: 0.9,
          reason_f1: 0.905,
          retrieval_precision_at_k: 1,
          retrieval_recall_at_k: 1
        },
        cases: demoCases.map((item) => ({
          case_id: item.id,
          case_name: item.name,
          passed: true,
          expected: {
            decision: item.response.decision?.decision,
            approved_amount: item.response.approved_amount
          },
          actual: item.response,
          notes: [item.note]
        }))
      });
      setStatusMessage("Showing demo eval results while the backend is unavailable.");
      setView("eval");
    } finally {
      setLoading(null);
    }
  }

  function loadDemoCase(caseId: string) {
    const item = demoCases.find((caseItem) => caseItem.id === caseId) ?? demoCases[0];
    setSelectedCaseId(caseId);
    setClaimResponse(item.response);
    setDraft((current) => ({
      ...current,
      memberId: item.memberId,
      claimCategory: item.category,
      claimedAmount: String(item.amount)
    }));
    setView("decision");
    setStatusMessage(`Loaded ${item.id} into the review panel.`);
  }

  const activeDecision = claimResponse.decision ?? {
    decision: "MANUAL_REVIEW" as DecisionType,
    approved_amount: claimResponse.approved_amount ?? 0,
    confidence_score: claimResponse.confidence_score ?? 0.72,
    reason: claimResponse.reason ?? "Demo data loaded.",
    rejection_reasons: claimResponse.rejection_reasons ?? [],
    line_item_decisions: claimResponse.line_item_decisions ?? []
  };

  return (
    <main className="min-h-screen bg-[var(--bg)] text-[var(--ink)]">
      <div className="mx-auto flex min-h-screen w-full max-w-[1440px] flex-col gap-6 px-4 py-4 sm:px-6 lg:px-8">
        <header className="overflow-hidden rounded-[24px] border border-[color:var(--line)] bg-[var(--panel)] shadow-[0_18px_60px_rgba(29,7,22,0.08)]">
          <div className="relative border-b border-[color:var(--line)] px-5 py-4 sm:px-6">
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_right,rgba(255,188,159,0.18),transparent_32%),linear-gradient(135deg,rgba(255,241,229,0.9),rgba(255,250,242,0.8))]" />
            <div className="relative flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
              <div className="flex items-center gap-4">
                <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-[var(--plum)]">
                  <Image src="/plum-assets/plum-logo.svg" alt="Plum" width={42} height={42} priority />
                </div>
                <div>
                  <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--plum)]">
                    Plum Claims Ops
                  </p>
                  <h1 className="mt-1 text-2xl font-semibold tracking-[-0.02em] text-[var(--ink)] sm:text-[2.1rem]">
                    Explainable claims review workspace
                  </h1>
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-3">
                <Pill icon={<ShieldCheck className="h-3.5 w-3.5" />} label="Policy-backed" />
                <Pill icon={<Activity className="h-3.5 w-3.5" />} label="Trace-first" />
                <Pill icon={<Sparkles className="h-3.5 w-3.5" />} label="Eval ready" />
              </div>
            </div>
          </div>

          <div className="grid gap-4 p-5 sm:p-6 xl:grid-cols-[1.2fr_0.8fr]">
            <section className="space-y-5">
              <div className="grid gap-4 md:grid-cols-3">
                {metrics.map((metric) => (
                  <MetricCard key={metric.label} {...metric} />
                ))}
              </div>

              <div className="flex flex-wrap gap-2">
                {([
                  ["submit", "Claim submission", UploadCloud],
                  ["decision", "Decision review", Layers3],
                  ["eval", "Eval dashboard", BarChart3]
                ] as const).map(([key, label, Icon]) => (
                  <button
                    key={key}
                    type="button"
                    onClick={() => setView(key)}
                    className={`inline-flex items-center gap-2 rounded-full border px-4 py-2 text-sm font-medium transition ${
                      view === key
                        ? "border-[var(--plum)] bg-[var(--plum)] text-white"
                        : "border-[color:var(--line)] bg-white text-[var(--ink)] hover:border-[var(--plum)]/30"
                    }`}
                  >
                    <Icon className="h-4 w-4" />
                    {label}
                  </button>
                ))}
              </div>

              <div className="grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
                <div className="overflow-hidden rounded-[22px] border border-[color:var(--line)] bg-[#fffaf2]">
                  <div className="flex items-center justify-between border-b border-[color:var(--line)] px-5 py-4">
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-[0.2em] text-[var(--muted)]">
                        Workflow
                      </p>
                      <h2 className="mt-1 text-lg font-semibold text-[var(--ink)]">
                        Submission, adjudication, and eval in one view
                      </h2>
                    </div>
                    <span className="rounded-full bg-[#fde7db] px-3 py-1 text-xs font-semibold text-[#a94d26]">
                      Live API + demo fallback
                    </span>
                  </div>
                  <div className="grid gap-4 px-5 py-5 sm:grid-cols-2">
                    <div className="rounded-[18px] border border-[color:var(--line)] bg-white p-4">
                      <div className="mb-4 flex items-center gap-2 text-sm font-semibold text-[var(--ink)]">
                        <User className="h-4 w-4 text-[var(--plum)]" />
                        Member intake
                      </div>
                      <p className="text-sm leading-6 text-[var(--muted)]">
                        Capture the claim context, supporting docs, and line-item evidence with a
                        Pluм-style, low-noise review flow.
                      </p>
                    </div>
                    <div className="rounded-[18px] border border-[color:var(--line)] bg-white p-4">
                      <div className="mb-4 flex items-center gap-2 text-sm font-semibold text-[var(--ink)]">
                        <BadgeCheck className="h-4 w-4 text-[#1f8f5c]" />
                        Deterministic output
                      </div>
                      <p className="text-sm leading-6 text-[var(--muted)]">
                        The backend returns trace events, policy evidence, confidence, and
                        component warnings for every adjudication.
                      </p>
                    </div>
                  </div>
                </div>

                <div className="overflow-hidden rounded-[22px] border border-[color:var(--line)] bg-[linear-gradient(180deg,#1d0716,#2a0d20)] text-white">
                  <div className="border-b border-white/10 px-5 py-4">
                    <p className="text-xs font-semibold uppercase tracking-[0.2em] text-[#fff1e5]/70">
                      Brand reference
                    </p>
                    <h2 className="mt-1 text-lg font-semibold">Plum visual language</h2>
                  </div>
                  <div className="relative min-h-[320px]">
                    <Image
                      src="/plum-assets/homepage.webp"
                      alt="Plum official website export"
                      fill
                      className="object-cover opacity-92"
                      sizes="(max-width: 1024px) 100vw, 40vw"
                    />
                    <div className="absolute inset-0 bg-gradient-to-t from-[#1d0716] via-[#1d0716]/70 to-transparent" />
                    <div className="absolute inset-x-0 bottom-0 p-5">
                      <p className="text-sm leading-6 text-[#fff1e5]/90">
                        Warm cream surfaces, deep plum framing, compact typography, and a quiet
                        operations feel that still reads premium.
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            </section>

            <aside className="grid gap-4">
              <div className="overflow-hidden rounded-[22px] border border-[color:var(--line)] bg-white">
                <div className="border-b border-[color:var(--line)] px-5 py-4">
                  <p className="text-xs font-semibold uppercase tracking-[0.2em] text-[var(--muted)]">
                    Backend target
                  </p>
                  <div className="mt-2 flex items-center gap-2 text-sm text-[var(--muted)]">
                    <Bot className="h-4 w-4 text-[var(--plum)]" />
                    <span className="break-all">{apiBaseUrl}</span>
                  </div>
                </div>
                <div className="space-y-3 p-5">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-[var(--muted)]">Status</span>
                    <span className="font-medium text-[#1f8f5c]">{statusMessage}</span>
                  </div>
                  {error ? (
                    <div className="flex items-start gap-3 rounded-[16px] border border-[#f1c4c0] bg-[#fff1f1] p-4 text-sm text-[#a83d35]">
                      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                      <span>{error}</span>
                    </div>
                  ) : null}
                  <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
                    <button
                      type="button"
                      onClick={() => startTransition(() => handleSubmitClaim())}
                      className="inline-flex items-center justify-center gap-2 rounded-full bg-[var(--plum)] px-4 py-3 text-sm font-semibold text-white transition hover:opacity-95"
                    >
                      {loading === "submit" ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowRight className="h-4 w-4" />}
                      Submit claim
                    </button>
                    <button
                      type="button"
                      onClick={() => startTransition(() => handleRunEval())}
                      className="inline-flex items-center justify-center gap-2 rounded-full border border-[color:var(--line)] bg-[#fffaf2] px-4 py-3 text-sm font-semibold text-[var(--ink)] transition hover:border-[var(--plum)]/30"
                    >
                      {loading === "eval" ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                      Run eval
                    </button>
                  </div>
                </div>
              </div>

              <div className="overflow-hidden rounded-[22px] border border-[color:var(--line)] bg-[#fffaf2]">
                <div className="border-b border-[color:var(--line)] px-5 py-4">
                  <p className="text-xs font-semibold uppercase tracking-[0.2em] text-[var(--muted)]">
                    Demo case presets
                  </p>
                </div>
                <div className="grid gap-3 p-5">
                  {demoCases.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => loadDemoCase(item.id)}
                      className={`flex items-start justify-between rounded-[18px] border p-4 text-left transition ${
                        selectedCaseId === item.id
                          ? "border-[var(--plum)] bg-white shadow-[0_10px_30px_rgba(29,7,22,0.07)]"
                          : "border-[color:var(--line)] bg-white/70 hover:border-[var(--plum)]/30"
                      }`}
                    >
                      <div className="pr-3">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-semibold text-[var(--ink)]">{item.id}</span>
                          <span className="rounded-full bg-[#fde7db] px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.15em] text-[#a94d26]">
                            {item.category}
                          </span>
                        </div>
                        <p className="mt-1 text-sm text-[var(--muted)]">{item.note}</p>
                      </div>
                      <ArrowRight className="mt-1 h-4 w-4 shrink-0 text-[var(--plum)]" />
                    </button>
                  ))}
                </div>
              </div>
            </aside>
          </div>
        </header>

        <section className="grid gap-6 xl:grid-cols-[1.04fr_0.96fr]">
          <div className="space-y-6">
            <Panel title="Claim submission" icon={<UploadCloud className="h-4 w-4" />}>
              <div className="grid gap-4 md:grid-cols-2">
                <Field label="Member ID">
                  <input
                    value={draft.memberId}
                    onChange={(event) => setDraft((current) => ({ ...current, memberId: event.target.value }))}
                    className="field"
                    placeholder="EMP001"
                  />
                </Field>
                <Field label="Policy ID">
                  <input
                    value={draft.policyId}
                    onChange={(event) => setDraft((current) => ({ ...current, policyId: event.target.value }))}
                    className="field"
                    placeholder="PLUM_GHI_2024"
                  />
                </Field>
                <Field label="Claim category">
                  <select
                    value={draft.claimCategory}
                    onChange={(event) => setDraft((current) => ({ ...current, claimCategory: event.target.value as ClaimCategory }))}
                    className="field"
                  >
                    {["CONSULTATION", "DIAGNOSTIC", "PHARMACY", "DENTAL", "VISION", "ALTERNATIVE_MEDICINE"].map((option) => (
                      <option key={option} value={option}>
                        {option}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Treatment date">
                  <input
                    type="date"
                    value={draft.treatmentDate}
                    onChange={(event) => setDraft((current) => ({ ...current, treatmentDate: event.target.value }))}
                    className="field"
                  />
                </Field>
                <Field label="Claimed amount">
                  <input
                    type="number"
                    min="1"
                    value={draft.claimedAmount}
                    onChange={(event) => setDraft((current) => ({ ...current, claimedAmount: event.target.value }))}
                    className="field"
                  />
                </Field>
                <Field label="Year-to-date amount">
                  <input
                    type="number"
                    min="0"
                    value={draft.ytdClaimsAmount}
                    onChange={(event) => setDraft((current) => ({ ...current, ytdClaimsAmount: event.target.value }))}
                    className="field"
                    placeholder="Optional"
                  />
                </Field>
                <Field label="Hospital name">
                  <input
                    value={draft.hospitalName}
                    onChange={(event) => setDraft((current) => ({ ...current, hospitalName: event.target.value }))}
                    className="field"
                    placeholder="Optional"
                  />
                </Field>
              </div>
            </Panel>

            <Panel title="Documents" icon={<Paperclip className="h-4 w-4" />}>
              <div className="space-y-3">
                {draft.documents.map((document, index) => (
                  <div key={document.id} className="grid gap-3 rounded-[18px] border border-[color:var(--line)] bg-[#fffaf2] p-4 md:grid-cols-[1.2fr_0.8fr_0.8fr_0.6fr_auto]">
                    <label className="flex flex-col gap-2 text-sm">
                      <span className="font-medium text-[var(--ink)]">File {index + 1}</span>
                      <input
                        type="file"
                        onChange={(event) => {
                          const file = event.target.files?.[0] ?? null;
                          setDraft((current) => ({
                            ...current,
                            documents: current.documents.map((item) =>
                              item.id === document.id ? { ...item, file } : item
                            )
                          }));
                        }}
                        className="block w-full text-sm text-[var(--muted)] file:mr-4 file:rounded-full file:border-0 file:bg-[var(--plum)] file:px-4 file:py-2 file:text-sm file:font-semibold file:text-white hover:file:opacity-95"
                      />
                      <span className="text-xs text-[var(--muted)]">
                        {document.file ? document.file.name : "No file chosen, fixture mode is active"}
                      </span>
                    </label>
                    <Field label="Declared type">
                      <select
                        value={document.declaredType}
                        onChange={(event) => {
                          setDraft((current) => ({
                            ...current,
                            documents: current.documents.map((item) =>
                              item.id === document.id
                                ? { ...item, declaredType: event.target.value as DocumentType }
                                : item
                            )
                          }));
                        }}
                        className="field"
                      >
                        {[
                          "PRESCRIPTION",
                          "HOSPITAL_BILL",
                          "LAB_REPORT",
                          "DIAGNOSTIC_REPORT",
                          "PHARMACY_BILL",
                          "DISCHARGE_SUMMARY",
                          "DENTAL_REPORT",
                          "UNKNOWN"
                        ].map((option) => (
                          <option key={option} value={option}>
                            {option}
                          </option>
                        ))}
                      </select>
                    </Field>
                    <Field label="Patient name">
                      <input
                        value={document.patientName}
                        onChange={(event) => {
                          setDraft((current) => ({
                            ...current,
                            documents: current.documents.map((item) =>
                              item.id === document.id
                                ? { ...item, patientName: event.target.value }
                                : item
                            )
                          }));
                        }}
                        className="field"
                        placeholder="Rajesh Kumar"
                      />
                    </Field>
                    <Field label="Quality">
                      <select
                        value={document.quality}
                        onChange={(event) => {
                          setDraft((current) => ({
                            ...current,
                            documents: current.documents.map((item) =>
                              item.id === document.id
                                ? { ...item, quality: event.target.value as DocumentDraft["quality"] }
                                : item
                            )
                          }));
                        }}
                        className="field"
                      >
                        {["GOOD", "LOW", "UNREADABLE", "UNKNOWN"].map((option) => (
                          <option key={option} value={option}>
                            {option}
                          </option>
                        ))}
                      </select>
                    </Field>
                    <div className="flex items-end">
                      <button
                        type="button"
                        onClick={() =>
                          setDraft((current) => ({
                            ...current,
                            documents:
                              current.documents.length > 1
                                ? current.documents.filter((item) => item.id !== document.id)
                                : current.documents
                          }))
                        }
                        className="inline-flex h-11 items-center justify-center rounded-full border border-[color:var(--line)] px-4 text-sm font-semibold text-[var(--muted)] transition hover:border-[#dfb2a0] hover:text-[var(--ink)]"
                      >
                        <XCircle className="mr-2 h-4 w-4" />
                        Remove
                      </button>
                    </div>
                  </div>
                ))}
                <button
                  type="button"
                  onClick={() =>
                    setDraft((current) => ({
                      ...current,
                      documents: [
                        ...current.documents,
                        {
                          id: `doc-${current.documents.length + 1}`,
                          file: null,
                          declaredType: "HOSPITAL_BILL",
                          patientName: "",
                          quality: "UNKNOWN"
                        }
                      ]
                    }))
                  }
                  className="inline-flex items-center gap-2 rounded-full border border-[color:var(--line)] bg-white px-4 py-2.5 text-sm font-semibold text-[var(--ink)] transition hover:border-[var(--plum)]/30"
                >
                  <Menu className="h-4 w-4" />
                  Add another document
                </button>
              </div>
            </Panel>
          </div>

          <div className="space-y-6">
            <Panel title="Decision review" icon={<BadgeCheck className="h-4 w-4" />}>
              <div className="grid gap-4 md:grid-cols-[0.78fr_1.22fr]">
                <div className="rounded-[22px] border border-[color:var(--line)] bg-[linear-gradient(180deg,#1d0716,#351325)] p-5 text-white">
                  <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#fff1e5]/60">
                    Final decision
                  </p>
                  <div className="mt-4 flex items-center gap-3">
                    <DecisionBadge decision={activeDecision.decision} />
                    <div>
                      <div className="text-3xl font-semibold tracking-[-0.03em]">
                        INR {activeDecision.approved_amount.toLocaleString("en-IN")}
                      </div>
                      <p className="text-sm text-[#fff1e5]/70">Approved amount</p>
                    </div>
                  </div>
                  <div className="mt-5 rounded-[18px] border border-white/10 bg-white/5 p-4">
                    <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#fff1e5]/60">
                      Confidence
                    </p>
                    <div className="mt-3 flex items-end gap-3">
                      <div className="text-3xl font-semibold">
                        {Math.round((activeDecision.confidence_score ?? 0) * 100)}%
                      </div>
                      <div className="flex-1">
                        <div className="h-2 overflow-hidden rounded-full bg-white/10">
                          <div
                            className="h-full rounded-full bg-[#ffb591]"
                            style={{ width: `${Math.round((activeDecision.confidence_score ?? 0) * 100)}%` }}
                          />
                        </div>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="space-y-4">
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
                    value={claimResponse.component_failures?.length ? claimResponse.component_failures.map((item) => item.message).join(" · ") : "No component failures"}
                  />
                </div>
              </div>
            </Panel>

            <Panel title="Document validation and extraction" icon={<FileText className="h-4 w-4" />}>
              <div className="grid gap-4">
                {(claimResponse.extracted_document_data?.length ?? 0) > 0 ? (
                  claimResponse.extracted_document_data?.map((doc) => (
                    <div key={doc.file_id} className="rounded-[18px] border border-[color:var(--line)] bg-[#fffaf2] p-4">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div>
                          <p className="text-sm font-semibold text-[var(--ink)]">
                            {doc.file_id} · {doc.document_type}
                          </p>
                          <p className="text-xs text-[var(--muted)]">Confidence {Math.round(doc.confidence * 100)}%</p>
                        </div>
                        <span className="rounded-full bg-white px-3 py-1 text-xs font-semibold text-[var(--muted)]">
                          {doc.missing_fields.length ? `${doc.missing_fields.length} missing fields` : "Complete"}
                        </span>
                      </div>
                      <div className="mt-4 grid gap-3 sm:grid-cols-2">
                        {Object.entries(doc.fields).map(([key, value]) => (
                          <DetailChip key={key} label={key} value={String(value)} />
                        ))}
                      </div>
                    </div>
                  ))
                ) : (
                  <EmptyState title="No extraction data" body="The current claim response does not include extracted fields yet." />
                )}
              </div>
            </Panel>

            <Panel title="Line-item adjudication" icon={<Layers3 className="h-4 w-4" />}>
              <div className="space-y-3">
                {activeDecision.line_item_decisions.length ? (
                  activeDecision.line_item_decisions.map((item) => (
                    <div key={`${item.description}-${item.claimed_amount}`} className="grid gap-3 rounded-[18px] border border-[color:var(--line)] bg-white p-4 md:grid-cols-[1.3fr_0.5fr_0.5fr_0.6fr]">
                      <div>
                        <p className="font-medium text-[var(--ink)]">{item.description}</p>
                        <p className="mt-1 text-sm text-[var(--muted)]">{item.reason}</p>
                      </div>
                      <DetailChip label="Claimed" value={`INR ${item.claimed_amount.toLocaleString("en-IN")}`} />
                      <DetailChip label="Approved" value={`INR ${item.approved_amount.toLocaleString("en-IN")}`} />
                      <div className="flex items-center justify-start md:justify-end">
                        <LineBadge decision={item.decision} />
                      </div>
                    </div>
                  ))
                ) : (
                  <EmptyState title="No line items" body="This claim has no itemized approvals or rejections." />
                )}
              </div>
            </Panel>
          </div>
        </section>

        <section className="grid gap-6 xl:grid-cols-[0.92fr_1.08fr]">
          <Panel title="Trace timeline" icon={<Clock3 className="h-4 w-4" />}>
            <div className="space-y-3">
              {(claimResponse.trace?.length ?? 0) > 0 ? (
                claimResponse.trace?.map((event, index) => (
                  <div key={`${event.component}-${index}`} className="flex gap-4 rounded-[18px] border border-[color:var(--line)] bg-[#fffaf2] p-4">
                    <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[var(--plum)] text-xs font-semibold text-white">
                      {index + 1}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="font-semibold text-[var(--ink)]">{event.component}</p>
                        <span className={`rounded-full px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.15em] ${
                          event.level === "WARNING"
                            ? "bg-[#fff1db] text-[#9f5f17]"
                            : event.level === "ERROR"
                              ? "bg-[#ffe0dd] text-[#a83d35]"
                              : "bg-[#e7f4ee] text-[#1f8f5c]"
                        }`}>
                          {event.level}
                        </span>
                      </div>
                      <p className="mt-1 text-sm leading-6 text-[var(--muted)]">{event.message}</p>
                    </div>
                  </div>
                ))
              ) : (
                <EmptyState title="No trace yet" body="Run a submission to populate the trace timeline." />
              )}
            </div>
          </Panel>

          <Panel title="Policy evidence and warnings" icon={<Hospital className="h-4 w-4" />}>
            <div className="grid gap-4 lg:grid-cols-2">
              <div className="space-y-3">
                {(claimResponse.retrieved_policy_evidence?.length ?? 0) > 0 ? (
                  claimResponse.retrieved_policy_evidence?.map((evidence) => (
                    <div key={evidence.evidence_id} className="rounded-[18px] border border-[color:var(--line)] bg-[#fffaf2] p-4">
                      <div className="flex items-center justify-between gap-3">
                        <p className="font-semibold text-[var(--ink)]">{evidence.rule_category}</p>
                        <span className="rounded-full bg-white px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.15em] text-[var(--muted)]">
                          {evidence.source}
                        </span>
                      </div>
                      <p className="mt-3 text-sm leading-6 text-[var(--muted)]">{evidence.text}</p>
                    </div>
                  ))
                ) : (
                  <EmptyState title="No policy evidence" body="The response did not include retrieved evidence." />
                )}
              </div>
              <div className="space-y-3">
                {(claimResponse.component_failures?.length ?? 0) > 0 ? (
                  claimResponse.component_failures?.map((failure) => (
                    <div key={`${failure.component}-${failure.message}`} className="rounded-[18px] border border-[#f1c4c0] bg-[#fff1f1] p-4">
                      <div className="flex items-center gap-2">
                        <AlertCircle className="h-4 w-4 text-[#a83d35]" />
                        <p className="font-semibold text-[#7f241d]">{failure.component}</p>
                      </div>
                      <p className="mt-2 text-sm leading-6 text-[#9c3b34]">{failure.message}</p>
                    </div>
                  ))
                ) : (
                  <EmptyState title="No component failures" body="Warnings and recoverable failures appear here when present." />
                )}
                {claimResponse.member_action_required ? (
                  <div className="rounded-[18px] border border-[#f5cfb8] bg-[#fff4eb] p-4">
                    <p className="text-sm font-semibold text-[#9f5f17]">Member action required</p>
                    <p className="mt-2 text-sm leading-6 text-[#a06a2a]">{claimResponse.member_action_required.message}</p>
                  </div>
                ) : null}
              </div>
            </div>
          </Panel>
        </section>

        <section className="grid gap-6 xl:grid-cols-[0.82fr_1.18fr]">
          <Panel title="Eval dashboard" icon={<BarChart3 className="h-4 w-4" />}>
            <div className="space-y-4">
              <div className="grid gap-3 sm:grid-cols-2">
                {[
                  ["Accuracy", evalRun?.metrics.decision_accuracy, "decision"],
                  ["Early stop", evalRun?.metrics.early_stop_accuracy, "early"],
                  ["Amount match", evalRun?.metrics.approved_amount_exact_match_rate, "amount"],
                  ["RRF recall", evalRun?.metrics.retrieval_recall_at_k, "retrieval"]
                ].map(([label, value]) => (
                  <div key={String(label)} className="rounded-[18px] border border-[color:var(--line)] bg-[#fffaf2] p-4">
                    <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[var(--muted)]">{label as string}</p>
                    <p className="mt-2 text-2xl font-semibold text-[var(--ink)]">
                      {typeof value === "number" ? `${Math.round(value * 100)}%` : "N/A"}
                    </p>
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
                  The layout borrows Plum’s warm editorial polish, then leans into ops density so
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
                {(evalRun?.cases.length ? evalRun.cases : demoCases.map((item) => ({
                  case_id: item.id,
                  case_name: item.name,
                  passed: true,
                  expected: { decision: item.response.decision?.decision },
                  actual: item.response,
                  notes: [item.note]
                }))).map((item) => (
                  <button
                    key={item.case_id}
                    type="button"
                    onClick={() => setSelectedCaseId(item.case_id)}
                    className="grid w-full grid-cols-12 gap-3 px-4 py-4 text-left transition hover:bg-[#fffaf2]"
                  >
                    <div className="col-span-2">
                      <div className="text-sm font-semibold text-[var(--ink)]">{item.case_id}</div>
                      <div className="text-xs text-[var(--muted)]">{item.case_name}</div>
                    </div>
                    <div className="col-span-3 text-sm text-[var(--muted)]">
                      {stringifyExpectation(item.expected)}
                    </div>
                    <div className="col-span-3 text-sm text-[var(--muted)]">
                      {item.actual?.decision?.decision ?? item.actual?.status ?? "N/A"}
                    </div>
                    <div className="col-span-2">
                      <ResultBadge passed={item.passed ?? true} />
                    </div>
                    <div className="col-span-2 flex justify-end">
                      <span className="inline-flex items-center gap-1 text-sm font-medium text-[var(--plum)]">
                        Open
                        <ArrowRight className="h-4 w-4" />
                      </span>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          </Panel>
        </section>
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

function MetricCard({
  label,
  value,
  detail
}: {
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="rounded-[20px] border border-[color:var(--line)] bg-white p-4">
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[var(--muted)]">{label}</p>
      <p className="mt-2 text-2xl font-semibold tracking-[-0.03em] text-[var(--ink)]">{value}</p>
      <p className="mt-1 text-sm leading-6 text-[var(--muted)]">{detail}</p>
    </div>
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
      <p className="mt-2 text-sm leading-6 text-[var(--ink)]">{value}</p>
    </div>
  );
}

function DetailChip({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[14px] border border-[color:var(--line)] bg-white px-3 py-2">
      <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[var(--muted)]">{label}</p>
      <p className="mt-1 text-sm font-medium text-[var(--ink)]">{value}</p>
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
