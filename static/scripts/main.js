// Simple animation for buttons
document.querySelectorAll('.btn').forEach(btn => {
  btn.addEventListener('mousedown', () => {
      btn.style.transform = 'translateY(1px)';
  });
  btn.addEventListener('mouseup', () => {
      btn.style.transform = 'translateY(-1px)';
  });
  btn.addEventListener('mouseleave', () => {
      btn.style.transform = '';
  });
});