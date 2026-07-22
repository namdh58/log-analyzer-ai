// Minimal PPTX-style slide controller. No framework, no build step.
const slides = Array.from(document.querySelectorAll(".slide"));
const total = slides.length;
let current = 0;

const dotsEl = document.getElementById("dots");
const progressEl = document.getElementById("progress");
const numEls = document.querySelectorAll(".slide-num-value");

slides.forEach((_, i) => {
  const dot = document.createElement("button");
  dot.className = "dot";
  dot.setAttribute("aria-label", `Go to slide ${i + 1}`);
  dot.addEventListener("click", () => goTo(i));
  dotsEl.appendChild(dot);
});
const dots = Array.from(dotsEl.children);

function render() {
  slides.forEach((slide, i) => {
    slide.classList.remove("active", "prev", "next");
    if (i === current) slide.classList.add("active");
    else if (i < current) slide.classList.add("prev");
    else slide.classList.add("next");
  });
  dots.forEach((d, i) => d.classList.toggle("active", i === current));
  progressEl.style.width = `${((current + 1) / total) * 100}%`;
  numEls.forEach((el) => (el.textContent = `${current + 1} / ${total}`));
}

function goTo(i) {
  current = Math.max(0, Math.min(total - 1, i));
  render();
}
function next() { goTo(current + 1); }
function prev() { goTo(current - 1); }

document.getElementById("btn-prev").addEventListener("click", prev);
document.getElementById("btn-next").addEventListener("click", next);

window.addEventListener("keydown", (e) => {
  switch (e.key) {
    case "ArrowRight":
    case " ":
    case "PageDown":
      e.preventDefault();
      next();
      break;
    case "ArrowLeft":
    case "PageUp":
      e.preventDefault();
      prev();
      break;
    case "Home":
      e.preventDefault();
      goTo(0);
      break;
    case "End":
      e.preventDefault();
      goTo(total - 1);
      break;
  }
});

// Click left/right thirds of the deck to navigate (mouse-friendly, PPTX-like).
document.querySelector(".deck").addEventListener("click", (e) => {
  if (e.target.closest("button, a")) return;
  const rect = e.currentTarget.getBoundingClientRect();
  const x = e.clientX - rect.left;
  if (x < rect.width * 0.25) prev();
  else if (x > rect.width * 0.75) next();
});

render();
