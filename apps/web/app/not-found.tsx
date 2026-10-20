import { Button, Card, CardBody, CardHeader } from "@autobacklinker/ui";
import Link from "next/link";

export default function NotFound() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-surface-sunken p-4">
      <Card className="w-full max-w-md">
        <CardHeader title="Page not found" description="The requested route does not exist." />
        <CardBody>
          <Link href="/">
            <Button>Back to the overview</Button>
          </Link>
        </CardBody>
      </Card>
    </div>
  );
}
