import { AuthGate } from "@/components/sites/marketlens/AuthGate";
import { Header } from "@/components/sites/marketlens/Header";
import { HomeScreen } from "@/components/sites/marketlens/HomeScreen";

export default function Home() {
  return (
    <>
      <Header />
      <main className="flex flex-1 flex-col">
        <AuthGate>
          <HomeScreen />
        </AuthGate>
      </main>
    </>
  );
}
