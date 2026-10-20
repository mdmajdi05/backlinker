"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Button, Card, CardBody, CardHeader, Field, Input } from "@autobacklinker/ui";
import { useAuth } from "@/lib/auth";
import { errorMessage } from "@/lib/api";

export default function RegisterPage() {
  return (
    <React.Suspense fallback={<Card><CardBody className="py-8 text-center text-sm text-content-muted">Loading…</CardBody></Card>}>
      <RegisterForm />
    </React.Suspense>
  );
}

function RegisterForm() {
  const router = useRouter();
  const params = useSearchParams();
  const { register } = useAuth();

  const [name, setName] = React.useState("");
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
      await register({ name: name.trim(), email: email.trim(), password });
      router.replace(nextPath);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setPending(false);
    }
  };

  return (
    <Card>
      <CardHeader title="Create account" description="Set up your workspace owner account." />
      <CardBody>
        <form onSubmit={onSubmit} className="space-y-3" noValidate>
          <Field label="Full name" required>
            <Input
              type="text"
              name="name"
              autoComplete="name"
              required
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Ada Lovelace"
            />
          </Field>

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

          <Field label="Password" required hint="At least 8 characters.">
            <Input
              type="password"
              name="password"
              autoComplete="new-password"
              required
              minLength={8}
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
            Create account
          </Button>
        </form>

        <p className="mt-4 text-center text-xs text-content-muted">
          Already registered?{" "}
          <Link
            href={nextPath && nextPath !== "/" ? `/login?next=${encodeURIComponent(nextPath)}` : "/login"}
            className="font-medium text-accent hover:underline"
          >
            Sign in
          </Link>
        </p>
      </CardBody>
    </Card>
  );
}
