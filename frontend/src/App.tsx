import { BrowserRouter, Route, Routes } from "react-router-dom";
import Home from "./pages/Home";
import Metrics from "./pages/Metrics";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/metricas" element={<Metrics />} />
      </Routes>
    </BrowserRouter>
  );
}
