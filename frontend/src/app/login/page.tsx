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
    <main className="flex min-h-screen bg-[#F8FAFC]">
      {/* Left branding panel */}
      <div className="hidden w-5/12 flex-col justify-between bg-gradient-to-br from-[#24354c] to-[#1a2638] p-12 lg:flex relative overflow-hidden">
        <div className="absolute top-[-20%] left-[-10%] w-[80%] h-[80%] rounded-full bg-[radial-gradient(circle,rgba(34,211,238,0.15)_0%,transparent_70%)] blur-[60px]"></div>
        <div className="absolute bottom-[-10%] right-[-10%] w-[60%] h-[60%] rounded-full bg-[radial-gradient(circle,rgba(16,185,129,0.1)_0%,transparent_70%)] blur-[40px]"></div>
        
        <div className="relative z-10">
          <div className="flex items-center gap-3">
            <div className="relative flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-[#22D3EE] via-[#0891B2] to-[#0E7490] shadow-[inset_0_0_0_1px_rgba(255,255,255,0.34),0_8px_18px_-10px_rgba(8,145,178,0.9)]">
              <div className="h-[18px] w-[18px] rotate-45 rounded-[3px] bg-[#F8FAFC]"></div>
              <div className="absolute bottom-[6px] right-[6px] h-2 w-2 rounded-full bg-[#0F172A]"></div>
            </div>
            <span className="font-heading text-2xl font-semibold tracking-[-0.02em] text-[#F8FAFC]">
              DealFlow<span className="text-[#22D3EE]">360</span>
            </span>
          </div>
          <h1 className="mt-16 font-heading text-4xl font-bold leading-[1.1] text-white">
            Intelligent quoting <br />
            <span className="text-[#9CAABC]">without the friction.</span>
          </h1>
          <p className="mt-6 text-[15px] leading-relaxed text-[#9CAABC] max-w-[400px]">
            Automated discount rules, dynamic risk scoring, and unified catalog management for high-velocity sales teams.
          </p>
        </div>
        
        <div className="relative z-10 border-t border-white/10 pt-8">
          <p className="text-sm text-[#6b7d92]">
            &copy; {new Date().getFullYear()} Acme Corp.
          </p>
        </div>
      </div>

      {/* Right form panel */}
      <div className="flex flex-1 flex-col justify-center p-8 sm:p-16 lg:p-24 animate-dfIn">
        <div className="mx-auto w-full max-w-[420px]">
          <div className="mb-10 text-center lg:text-left">
            <h2 className="font-heading text-3xl font-bold tracking-[-0.02em] text-[#0F172A]">
              Welcome back
            </h2>
            <p className="mt-2 text-[14px] text-[#64748B]">
              Enter your details to access your workspace.
            </p>
          </div>

          <div className="mb-8 flex rounded-[10px] bg-[#F1F5F9] p-1">
            {(["login", "signup"] as const).map((value) => (
              <button
                key={value}
                onClick={() => setMode(value)}
                className={`flex-1 rounded-[8px] py-2 text-[13px] font-medium transition ${
                  mode === value
                    ? "bg-white text-[#0F172A] shadow-sm"
                    : "text-[#64748B] hover:text-[#0F172A]"
                }`}
              >
                {value === "login" ? "Log In" : "Sign Up"}
              </button>
            ))}
          </div>

          <form onSubmit={submit} className="space-y-5">
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
                  hint="Roles live in our database, not the identity provider."
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

            <div className="space-y-5">
              <Field label="Email address">
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
              <p className="rounded-[8px] border border-[#FECACA] bg-[#FEF2F2] px-4 py-3 text-[13px] text-[#DC2626]">
                {error}
              </p>
            )}

            <Button type="submit" disabled={busy} className="w-full mt-2">
              {busy ? "Please wait…" : mode === "login" ? "Log in to workspace" : "Create Account"}
            </Button>
          </form>

          <div className="mt-8">
            <Note>
              After login, internal users land on the Sales Dashboard. Customers land on their
              Quotation Portal.
            </Note>
          </div>

          <div className="mt-10 border-t border-[#E2E8F0] pt-8">
            <p className="mb-4 text-center text-[12px] font-medium uppercase tracking-[0.05em] text-[#64748B]">
              Seeded demo accounts (pw: dealflow)
            </p>
            <div className="flex flex-wrap justify-center gap-[6px]">
              {DEMO_LOGINS.map((demo) => (
                <button
                  key={demo.email}
                  onClick={() => {
                    setMode("login");
                    setEmail(demo.email);
                    setPassword("dealflow");
                  }}
                  className="rounded-[6px] border border-[#CBD5E1] bg-white px-[10px] py-[6px] text-[12px] text-[#475569] shadow-[inset_0_1px_2px_rgba(0,0,0,0.02)] transition hover:border-[#0891B2] hover:text-[#0891B2]"
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
