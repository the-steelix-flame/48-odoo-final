"use client";

/** Screen 1 — Login / Signup.  Owner: sinjeki. */

import { useState } from "react";
import { useRouter } from "next/navigation";

import { ApiError } from "@/lib/api";
import { landingPathFor, useAuth } from "@/lib/auth";
import { Button, Field, Note, inputClass } from "@/components/ui";
import type { Role } from "@/types";

const DEMO_LOGINS: { email: string; label: string }[] = [
  { email: "rep@dealflow360.test", label: "Sales Rep" },
  { email: "manager@dealflow360.test", label: "Sales Manager" },
  { email: "finance@dealflow360.test", label: "Finance / Ops" },
  { email: "admin@dealflow360.test", label: "Admin" },
  { email: "buyer@acme.test", label: "Customer (portal)" },
];

const SIGNUP_ROLES: { value: Role; label: string }[] = [
  { value: "SALES_REP", label: "Sales Rep" },
  { value: "SALES_MANAGER", label: "Sales Manager" },
  { value: "FINANCE", label: "Finance / Operations" },
  { value: "ADMIN", label: "Admin" },
  { value: "CUSTOMER", label: "Customer (portal user)" },
];

export default function LoginPage() {
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("rep@dealflow360.test");
  const [password, setPassword] = useState("dealflow");
  const [fullName, setFullName] = useState("");
  const [role, setRole] = useState<Role>("SALES_REP");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const { login, signup } = useAuth();
  const router = useRouter();

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const user =
        mode === "login"
          ? await login(email, password)
          : await signup(email, password, fullName || email, role);
      router.push(landingPathFor(user.role));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center px-4 py-10">
      <div className="w-full max-w-xl">
        <div className="rounded-t-xl border border-edge bg-slate-300 px-6 py-3 text-center text-sm font-semibold text-slate-900">
          DealFlow360
        </div>

        <div className="rounded-b-xl border border-t-0 border-edge bg-surface p-6">
          <h1 className="text-xl font-semibold text-slate-100">Login / Signup</h1>
          <p className="mt-1 text-xs text-slate-400">
            Entry point for internal users and customers
          </p>

          <div className="mt-5 flex gap-2">
            {(["login", "signup"] as const).map((value) => (
              <button
                key={value}
                onClick={() => setMode(value)}
                className={`rounded-lg px-4 py-1.5 text-sm transition ${
                  mode === value
                    ? "bg-brand text-white"
                    : "border border-edge text-slate-300 hover:bg-white/5"
                }`}
              >
                {value === "login" ? "Log In" : "Sign Up"}
              </button>
            ))}
          </div>

          <form onSubmit={submit} className="mt-5 space-y-4">
            {mode === "signup" && (
              <>
                <Field label="Full name">
                  <input
                    className={inputClass}
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                    required
                  />
                </Field>
                <Field
                  label="Role"
                  hint="Roles live in our database, not the identity provider — that's what makes the Firebase swap a one-file change."
                >
                  <select
                    className={inputClass}
                    value={role}
                    onChange={(e) => setRole(e.target.value as Role)}
                  >
                    {SIGNUP_ROLES.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </Field>
              </>
            )}

            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Email">
                <input
                  type="email"
                  className={inputClass}
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                />
              </Field>
              <Field label="Password">
                <input
                  type="password"
                  className={inputClass}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
              </Field>
            </div>

            {error && (
              <p className="rounded-lg border border-rose-800 bg-rose-950/30 px-3 py-2 text-sm text-rose-300">
                {error}
              </p>
            )}

            <Button type="submit" disabled={busy}>
              {busy ? "Please wait…" : mode === "login" ? "Log In" : "Create Account"}
            </Button>
          </form>

          <div className="mt-5">
            <Note>
              After login, internal users land on the Sales Dashboard. Customers land on their
              Quotation Portal.
            </Note>
          </div>

          <div className="mt-5 border-t border-edge pt-4">
            <p className="mb-2 text-xs font-medium text-slate-400">
              Seeded demo accounts — password <code className="text-slate-300">dealflow</code>
            </p>
            <div className="flex flex-wrap gap-2">
              {DEMO_LOGINS.map((demo) => (
                <button
                  key={demo.email}
                  onClick={() => {
                    setMode("login");
                    setEmail(demo.email);
                    setPassword("dealflow");
                  }}
                  className="rounded-lg border border-edge px-3 py-1.5 text-xs text-slate-300 hover:bg-white/5"
                >
                  {demo.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
