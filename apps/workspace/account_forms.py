from django import forms
from django.contrib.auth.forms import PasswordChangeForm


class SecurePasswordChangeForm(PasswordChangeForm):
    second_factor = forms.CharField(
        label="Código do autenticador ou de recuperação",
        max_length=32,
        required=False,
        widget=forms.TextInput(attrs={"autocomplete": "one-time-code"}),
    )

    def __init__(self, user, *args, mfa_enabled=False, **kwargs):
        super().__init__(user, *args, **kwargs)
        for name in ("old_password", "new_password1", "new_password2"):
            self.fields[name].max_length = 1024
        if mfa_enabled:
            self.fields["second_factor"].required = True
        else:
            self.fields.pop("second_factor")

    def clean_new_password2(self):
        password = self.cleaned_data.get("new_password2")
        if password == self.cleaned_data.get("old_password"):
            raise forms.ValidationError("Escolha uma senha diferente da atual.")
        return password
