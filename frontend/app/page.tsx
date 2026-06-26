import { Activity, ClipboardCheck, FileSearch } from "lucide-react";

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export default function Home() {
  return (
    <main className="min-h-screen bg-surface text-ink">
      <section className="mx-auto flex w-full max-w-6xl flex-col gap-8 px-6 py-8">
        <header className="flex flex-col gap-2 border-b border-slate-200 pb-5">
          <p className="text-sm font-semibold uppercase tracking-wide text-brand">Plum Claims Ops</p>
          <h1 className="text-3xl font-semibold">Explainable claim processing workspace</h1>
          <p className="max-w-3xl text-sm leading-6 text-slate-600">
            Phase 1 foundation is ready. Later phases will connect claim submission, document
            extraction, policy retrieval, deterministic adjudication, traces, and eval reporting.
          </p>
        </header>

        <div className="grid gap-4 md:grid-cols-3">
          <StatusCard
            icon={<ClipboardCheck aria-hidden className="h-5 w-5" />}
            title="Claim Intake"
            body="Submission form, document upload, and early validation will be implemented in Phase 4."
          />
          <StatusCard
            icon={<FileSearch aria-hidden className="h-5 w-5" />}
            title="Policy Evidence"
            body="Hybrid retrieval over policy terms and document guidance will be implemented in Phase 6."
          />
          <StatusCard
            icon={<Activity aria-hidden className="h-5 w-5" />}
            title="Eval Dashboard"
            body="The 12 assignment cases will be runnable from the UI once the backend pipeline lands."
          />
        </div>

        <section className="rounded-lg border border-slate-200 bg-white p-5">
          <h2 className="text-base font-semibold">Backend target</h2>
          <p className="mt-2 text-sm text-slate-600">{apiBaseUrl}</p>
        </section>
      </section>
    </main>
  );
}

function StatusCard({
  icon,
  title,
  body
}: {
  icon: React.ReactNode;
  title: string;
  body: string;
}) {
  return (
    <article className="rounded-lg border border-slate-200 bg-white p-5">
      <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-md bg-brand text-white">
        {icon}
      </div>
      <h2 className="text-base font-semibold">{title}</h2>
      <p className="mt-2 text-sm leading-6 text-slate-600">{body}</p>
    </article>
  );
}

