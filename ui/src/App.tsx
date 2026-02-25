import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { ProjectBoard } from "./pages/ProjectBoard";
import { ProjectList } from "./pages/ProjectList";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { refetchOnWindowFocus: false, retry: 1 },
  },
});

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<ProjectList />} />
          <Route path="/projects/:id" element={<ProjectBoard />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
