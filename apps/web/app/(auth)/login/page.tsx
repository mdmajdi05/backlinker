"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Button, Card, CardBody, CardHeader, Field, Input } from "@autobacklinker/ui";
import { useAuth } from "@/lib/auth";
import { errorMessage } from "@/lib/api";

export default function LoginPage() {
  return (
    <React.Suspense fallback={<Card><CardBody className="py-8 text-center text-sm text-content-muted">Loading…</CardBody></Card>}>
      <LoginForm />
    </React.Suspense>
  );
}

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const { login } = useAuth();

  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [pending, setPending] = React.useState(false);

  const nextPath = params.get("next") ?? "/";

  const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      await login({ email: email.trim(), password });
      router.replace(nextPath);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setPending(false);
    }
  };

  return (
    <Card>
      <CardHeader title="Sign in" description="Use your workspace account." />
      <CardBody>
        <form onSubmit={onSubmit} className="space-y-3" noValidate>
          <Field label="Email" required>
            <Input
              type="email"
              name="email"
              autoComplete="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="you@company.com"
            />
          </Field>

          <Field label="Password" required>
            <Input
              type="password"
              name="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </Field>

          {error ? (
            <p role="alert" className="rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-xs text-danger">
              {error}
            </p>
          ) : null}

          <Button type="submit" className="w-full" loading={pending}>
            Sign in
          </Button>
        </form>

        <p className="mt-4 text-center text-xs text-content-muted">
          No account yet?{" "}
          <Link
            href={nextPath && nextPath !== "/" ? `/register?next=${encodeURIComponent(nextPath)}` : "/register"}
            className="font-medium text-accent hover:underline"
          >
            Create one
          </Link>
        </p>
      </CardBody>
    </Card>
  );
}
