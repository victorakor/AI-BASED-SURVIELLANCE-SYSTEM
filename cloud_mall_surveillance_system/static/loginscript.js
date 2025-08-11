document.addEventListener("DOMContentLoaded", () => {
    // Get form elements and buttons once
    const signInForm = document.getElementById('signIn');
    const signUpForm = document.getElementById('signup');
    const signUpButton = document.getElementById('signUpButton');
    const signInButton = document.getElementById('signInButton');

    // Logic to toggle between sign-up and sign-in forms
    if (signUpButton && signInForm && signUpForm) {
        signUpButton.addEventListener('click', () => {
            signInForm.style.display = "none";
            signUpForm.style.display = "block";
        });
    }

    if (signInButton && signInForm && signUpForm) {
        signInButton.addEventListener('click', () => {
            signInForm.style.display = "block";
            signUpForm.style.display = "none";
        });
    }
});
