try {
    # Obtém a lista de idiomas atual configurada para o usuário
    $LanguageList = Get-WinUserLanguageList

    # Procura pelo idioma Português (Brasil) na lista
    $ptBR = $LanguageList | Where-Object LanguageTag -eq "pt-BR"

    # Verifica se o idioma pt-BR foi encontrado
    if ($ptBR) {
        # O código para o teclado "Estados Unidos (Internacional)" sob o idioma pt-BR é "0416:00020409"
        # 0416 = Português (Brasil) | 00020409 = Estados Unidos (Internacional)
        $USIntKeyboard = "0416:00020409"

        # Verifica se o teclado já não está na lista para evitar duplicidade
        if ($ptBR.InputMethodTips -notcontains $USIntKeyboard) {
            $ptBR.InputMethodTips.Add($USIntKeyboard)

            # Aplica a nova lista de idiomas no sistema
            Set-WinUserLanguageList $LanguageList -Force -ErrorAction Stop

            Write-Host "Teclado 'Estados Unidos (Internacional)' adicionado com sucesso ao idioma Portugues (Brasil)!" -ForegroundColor Green
        } else {
            Write-Host "O teclado 'Estados Unidos (Internacional)' ja esta configurado no idioma Portugues (Brasil)." -ForegroundColor Yellow
        }
        exit 0
    } else {
        Write-Host "[ERRO] O idioma Portugues (Brasil) (pt-BR) nao foi encontrado na lista de idiomas. Instale-o primeiro." -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "[ERRO] Falha ao configurar teclado: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
